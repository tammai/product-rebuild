#!/usr/bin/env python3
"""reference_guard.py — PreToolUse(Read|Grep|Glob|Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit): a
build lane may not read the reference checkout (unless the posture is own-code) or the hidden tests, and may
not write into the workbench (spec 05, P3 and P4).

WHY IT IS A HOOK. A lane that can read the reference's code copies it, and one that can read the
hidden tests builds to them; either turns parity and the hidden suite into the lane agreeing with
itself. A brief that says "do not look" is not a control, and lanes run as subagents of a session
that starts in the project's parent directory, where both paths sit one `cd ..` away.

WHO IS A LANE. A call from the `lane-worker` agent (the payload's `agent_type`), or any call in a
session whose root lies in a worktree of a repo listed in the workbench's repos.yaml (a lane run as
its own session). Everything else, the orchestrator and rspec's agents included, is not judged: under
`observe` the spec side is meant to read the reference.

WHAT IS DENIED. The per-user data folder that holds the hidden tests and the local config naming them
(hooklib.rebuild_data_dir), and every holdout folder that config names, under every posture and whether
or not they exist yet. The reference checkout unless `sources.yaml` `reference.posture` is own-code (empty
means own-code for `reference.kind: own-code`, else observe; an unknown value counts as strict, the
narrower reading): `reference.checkout`, plus the fallbacks scripts/preflight.py would find that are
git repos. A fallback that is, or holds, a repo listed in repos.yaml is never denied, because
`../<reference.name>` can be the rebuild's own repo when the two share a name. And any lane write into
the workbench: the guard reads its posture, project and lane list from workbench files (sources.yaml,
locks/pipeline.yaml, repos.yaml), and round 1 of the 3.0 review switched it off by editing them. A folder
with `locks/` but no readable `rebuild_major` marker counts as a workbench here (fails closed), because
deleting the marker once switched every 3.x guard off.

IT IS A GUARD, NOT A SANDBOX. Read, Grep, Glob and the write tools are judged by their path fields; a
search root or glob that holds a denied path counts. Bash is judged by the directory each simple command
runs in (after `cd`), by every word that resolves to a path (a glob, or an operand of a recursive reader,
that holds a denied path counts), by the write targets of writing commands, and by any denied path
spelled in the raw text in any separator or drive spelling, plus each holdout folder's own name. PowerShell
is judged by its words and raw text. Known limits, listed in the README and docs/MIGRATION-3.md: a path
computed at run time (`$X`, `$(…)`, `%LOCALAPPDATA%`), a script that opens the path itself, a recursive
reader or writer not listed below, a nested shell, a Windows short name (`PRODUCT~1`), or a tool other than
these is not seen. The list is not grown further: the hidden tests are kept out of reach by never giving a
lane their path, and this guard is the second line (P3: a guard, not a sandbox).

The deny message names no path: a lane reads it, and P4 says nothing a lane sees names the holdout.
Fails open outside a 3.x workbench; a crash inside a pipeline session blocks (guard_io).
"""

import os
import re
import sys

from guard_io import (
    read_payload, block_on_crash, tool_call, command_dir, command_walk, expand_home, emit_decision,
    real_path, utf8_stdio, prog_name, UNKNOWN, CASE_INSENSITIVE_FS,
)
from hooklib import (
    get, read_text, session_root, workbenches_near, listed_repos, pipeline_repo_of, is_current_workbench, _native,
    marker_unreadable, rebuild_data_dir, holdout_config,
)

GUARD = "reference_guard"
LANE_AGENT = re.compile(r"(?:^|:)lane-worker\Z")
POSTURES = ("strict", "observe", "own-code")
GLOB_CHARS = re.compile(r"[*?\[{]")
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
TOOLS = ("Read", "Grep", "Glob", "Bash", "PowerShell") + WRITE_TOOLS
DENY = ("Denied by product-rebuild's reference guard: a build lane may not read the reference product's code "
        "or the hidden tests, and writes only inside its own worktree. Build from your specs, the locked "
        "contracts and the open acceptance bundle; if they leave a behaviour unclear, raise it as a spec "
        "question instead of looking for the answer. Searching your own code? Give the search your worktree "
        "as its path.")

# Readers that walk a directory tree, so from an ancestor of a denied root they reach it. Those in RECURSIVE
# recurse by default, the others only with an -r/-R flag. `cd`, a plain `ls ..` and `git -C ..` stay allowed,
# so a lane can still move about the project parent.
RECURSIVE = {"rg", "ag", "ack", "find", "du", "tree", "tar", "zip", "7z", "rsync", "fd"}
SEARCHERS = {"rg", "ag", "ack", "grep", "egrep", "fgrep", "fd"}  # their first operand is the pattern
# Each program's own recursive short flags: `ls -ltr ..` only sorts by time, `cp -a` archives a tree.
RECURSIVE_WITH_FLAG = {"grep": "rR", "egrep": "rR", "fgrep": "rR", "cp": "rRa", "scp": "r", "ls": "R",
                       "chmod": "R", "chown": "R"}
# Commands whose path operands they write (sed and perl only with -i), and git subcommands that write the
# repo they run in.
WRITERS = {"cp", "mv", "tee", "rm", "rmdir", "touch", "mkdir", "ln", "rsync", "install", "truncate", "dd",
           "sed", "perl", "chmod", "chown", "unzip", "tar", "patch"}
GIT_WRITES = {"add", "commit", "checkout", "reset", "rm", "mv", "apply", "stash", "restore", "switch", "merge",
              "rebase", "pull", "am", "cherry-pick", "revert", "tag", "clean", "submodule", "config", "init"}
BOUNDARY_END = r"(?=$|[\\/\s\"';|&)`,])"


def _key(p):
    p = real_path(p)
    return os.path.normcase(p) if CASE_INSENSITIVE_FS else p


def _inside(path, roots):
    k = _key(path)
    return any(k == r or k.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def _holds(path, roots):
    """True when `path` is a directory that contains one of `roots`: a recursive search there reaches it."""
    k = _key(path).rstrip(os.sep) + os.sep
    return any(r.startswith(k) for r in roots)


def _sources_field(wb, key):
    # The same two-space `reference:` block validate.py and playbook.py parse; change them together.
    try:
        text = read_text(os.path.join(wb, "sources.yaml")) + "\n"
    except OSError:
        return ""
    block = re.search(r"^reference:[ \t]*\n((?:(?:[ \t]+.*)?\n)*)", text, re.M)
    f = block and re.search(rf"^[ \t]+{key}:[ \t]*(.*)$", block.group(1), re.M)
    return re.split(r"\s+#", f.group(1))[0].strip().strip("\"'") if f else ""


def posture_of(wb):
    posture = _sources_field(wb, "posture")
    if not posture:
        return "own-code" if _sources_field(wb, "kind") == "own-code" else "observe"
    return posture if posture in POSTURES else "strict"


def holdout_roots():
    """The data folder and every holdout folder the local config names, for any workbench: the config is
    per user, and a lane of one rebuild has no more business in another's hidden tests."""
    return [rebuild_data_dir()] + sorted(set(holdout_config().values()))


def denied_roots(wb):
    parent = os.path.dirname(wb)
    roots = holdout_roots()
    if posture_of(wb) != "own-code":
        own = {_key(r) for r in listed_repos([wb])}
        checkout = _sources_field(wb, "checkout")
        if checkout:
            roots.append(os.path.join(wb, _native(checkout)))
        name = _sources_field(wb, "name")
        for c in (os.path.join(wb, "reference"), os.path.join(parent, "reference"),
                  os.path.join(parent, name) if name else None):
            if c and os.path.exists(os.path.join(c, ".git")) and not _holds(c, own) and _key(c) not in own:
                roots.append(c)
    return [_key(r) for r in roots]


def is_lane(data):
    agent = get(data, "agent_type")
    if isinstance(agent, str) and LANE_AGENT.search(agent):
        return True
    return pipeline_repo_of(session_root(data), data) is not None


def _resolve(word, base):
    p = expand_home(word)
    if os.path.isabs(p):
        return p
    return os.path.join(base, p) if base else None


def _judge(path, roots, recursive):
    """One rule for every candidate path, from Bash and from the tools alike. A glob is cut back to the
    directory the shell or the tool lists (`../p-hold*/x` lists `..`), and a listed or recursively searched
    directory that holds a root reaches it. Round 1 of the 3.0 review got past the guard with exactly those
    two shapes (`cat ../p-hold*/http/*.yaml`, `grep -r x ..`)."""
    if GLOB_CHARS.search(path):
        head = GLOB_CHARS.split(path, 1)[0]
        cut = max(head.rfind("/"), head.rfind("\\"))
        path = head[:cut] if cut > 0 else (head[:1] if cut == 0 else ".")
        recursive = True
    return _inside(path, roots) or (recursive and _holds(path, roots))


def _recursive(prog, argv):
    if prog in RECURSIVE:
        return True
    flags = RECURSIVE_WITH_FLAG.get(prog)
    return bool(flags) and any(
        a in ("--recursive", "--dereference-recursive", "--archive")
        or (re.match(r"^-[a-zA-Z]+$", a) is not None and any(f in a[1:] for f in flags)) for a in argv[1:])


def _in_place(argv):
    """sed's and perl's in-place edit, however it is spelled: -i, -i.bak, -Ei, -pi, -i -e, --in-place[=sfx]."""
    return any(a.startswith("--in-place") or (re.match(r"^-[a-zA-Z]*i", a) is not None) for a in argv[1:])


def _root_pattern(root):
    """A regex for `root` in any spelling a command can carry: separators doubled, escaped (`\\\\` in a
    Python literal) or mixed, `./` segments, and on Windows the drive as `C:`, `/c`, `/cygdrive/c`, `/mnt/c`,
    `\\\\?\\C:` or `\\\\localhost\\c$`. Enumerating three spellings missed each of these in round 1."""
    sep = r"[\\/]+(?:\.[\\/]+)*"
    m = re.match(r"^([a-zA-Z]):[\\/](.*)", root)
    if m:
        d = m.group(1).lower()
        head = rf"(?:{d}:|/{d}|/cygdrive/{d}|/mnt/{d}|[\\/]{{2}}\?[\\/]+{d}:|[\\/]{{2}}localhost[\\/]+{d}\$)"
        rest = m.group(2)
    else:
        head, rest = "", root
    return head + "".join(sep + re.escape(p) for p in re.split(r"[\\/]+", rest) if p) + BOUNDARY_END


def raw_reaches(command, roots, holdout_names):
    """The raw text, for a spelling the tokenizer leaves unresolved (inside a quoted script, an
    interpreter's -c, a heredoc). A holdout folder's own name (`<project>-<random hex>`) is denied at a path
    boundary in any form, relative spellings included: it is unique by construction and a lane is never
    told it (P4), so no lane command has a reason to spell it."""
    flags = re.I if CASE_INSENSITIVE_FS else 0
    if any(re.search(_root_pattern(r), command, flags) for r in roots):
        return True
    return any(re.search(r"(?:^|[\\/\s\"'=(`])" + re.escape(n) + BOUNDARY_END, command, re.I) for n in holdout_names)


def _git_locations(argv):
    out = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a in ("-C", "--git-dir", "--work-tree")]
    return out + [a.split("=", 1)[1] for a in argv if a.startswith(("--git-dir=", "--work-tree="))]


def _writes_into(prog, argv, targets, base, workbenches):
    paths = list(targets)
    if prog == "git":
        locs = _git_locations(argv)
        sub = next((a for i, a in enumerate(argv[1:], 1) if not a.startswith("-") and argv[i - 1] not in ("-C", "--git-dir", "--work-tree", "-c")), "")
        if sub in GIT_WRITES:
            paths += locs or ["."]
    elif prog in WRITERS and (prog not in ("sed", "perl") or _in_place(argv)):
        paths += [a.split("=", 1)[1] if prog == "dd" and "=" in a else a
                  for a in argv[1:] if a and not a.startswith("-")]
    for w in paths:
        p = None if UNKNOWN in w else _resolve(w, base)
        if p and _inside(p, workbenches):
            return True
    return False


def bash_reaches(command, cwd, roots, holdout_names=(), workbenches=()):
    for c in command_walk(command, cwd):
        d = c["dir"]
        if d and _inside(d, roots):
            return True
        argv = [a for a in c["argv"] if isinstance(a, str)]
        prog = prog_name(argv[0]) if argv else ""
        recursive = _recursive(prog, argv)
        operands = [a for a in argv[1:] if a and not a.startswith("-")]
        if recursive and d and len(operands) <= (1 if prog in SEARCHERS else 0) and _holds(d, roots):
            return True  # `rg x` or `find` with no path searches the directory it runs in
        targets = [r.get("target") for r in c["redirects"] if isinstance(r.get("target"), str)]
        for w in argv[1:] + targets:
            if not w or UNKNOWN in w:
                continue
            for cand in ([w.split("=", 1)[1]] if "=" in w else []) + ([] if w.startswith("-") else [w]):
                p = _resolve(cand, d or cwd)
                if p and _judge(p, roots, recursive and prog not in ("cd", "pushd")):
                    return True
        if d and workbenches and _writes_into(prog, argv, targets, d, workbenches):
            return True
    return raw_reaches(command, roots, holdout_names)


def powershell_reaches(command, cwd, roots, holdout_names=(), workbenches=()):
    """The PowerShell tool (Claude Code on Windows) is a second general shell. Its syntax is not bash's, so
    words are split on whitespace and separators rather than parsed: every word is judged as a path, any
    word as a search root under -Recurse, and with a writing cmdlet any word in the workbench is a write."""
    words = [w.strip("\"'()") for w in re.split(r"[\s;|&{}]+", command)]
    words = [re.sub(r"^-\w+:", "", w) for w in words if w and not w.startswith("$")]
    recursive = any(w.lower() in ("-recurse", "-r") for w in words)
    writes = re.search(r"\b(?:Set-Content|Add-Content|Out-File|Copy-Item|Move-Item|Remove-Item|New-Item|"
                       r"Rename-Item|Clear-Content|cp|mv|rm|ni|del|copy|move)\b|>", command, re.I)
    for w in words:
        if not w or w.startswith("-"):
            continue
        p = _resolve(w, cwd)
        if p and (_judge(p, roots, recursive) or (writes and workbenches and _inside(p, workbenches))):
            return True
    return raw_reaches(command, roots, holdout_names)


def tool_reaches(name, inp, cwd, roots):
    base = get(inp, "path")
    base = _resolve(base, cwd) if isinstance(base, str) and base else cwd
    if name == "Read":
        target = get(inp, "file_path")
        return isinstance(target, str) and bool(target) and _judge(_resolve(target, cwd), roots, False)
    if _judge(base, roots, True):
        return True
    pattern = get(inp, "pattern")
    if name == "Glob" and isinstance(pattern, str) and pattern:
        return _judge(_resolve(pattern, base), roots, True)
    return False


def write_reaches(inp, cwd, roots, workbenches):
    target = get(inp, "file_path") or get(inp, "notebook_path")
    if not isinstance(target, str) or not target:
        return False
    p = _resolve(target, cwd)
    return bool(p) and (_inside(p, roots) or _inside(p, workbenches))


def main():
    utf8_stdio()
    data = read_payload(GUARD)
    block_on_crash(GUARD, data)
    call = tool_call(data)
    if call.name not in TOOLS or not is_lane(data):
        return 0
    wbs = workbenches_near(session_root(data), lambda d: is_current_workbench(d) or marker_unreadable(d))
    roots = list(dict.fromkeys(r for wb in wbs for r in denied_roots(wb)))
    if not roots:
        return 0
    names = sorted({os.path.basename(h.rstrip(r"\/")) for h in holdout_config().values()})
    wb_keys = [_key(wb) for wb in wbs]
    cwd = command_dir(data)
    command = get(call.input, "command")
    if call.name == "Bash":
        hit = isinstance(command, str) and bash_reaches(command, cwd, roots, names, wb_keys)
    elif call.name == "PowerShell":
        hit = isinstance(command, str) and powershell_reaches(command, cwd, roots, names, wb_keys)
    elif call.name in WRITE_TOOLS:
        hit = write_reaches(call.input, cwd, roots, wb_keys)
    else:
        hit = tool_reaches(call.name, call.input, cwd, roots)
    if hit:
        emit_decision("deny", DENY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
