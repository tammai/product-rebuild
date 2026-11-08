#!/usr/bin/env python3
"""reference_guard.py — PreToolUse(Read|Grep|Glob|Bash): a build lane may not read the reference
checkout (unless the posture is own-code) or the hidden tests (spec 05, P3 and P4).

WHY IT IS A HOOK. A lane that can read the reference's code copies it, and one that can read the
hidden tests builds to them; either turns parity and the hidden suite into the lane agreeing with
itself. A brief that says "do not look" is not a control, and lanes run as subagents of a session
that starts in the project's parent directory, where both paths sit one `cd ..` away.

WHO IS A LANE. A call from the `lane-worker` agent (the payload's `agent_type`), or any call in a
session whose root lies in a worktree of a repo listed in the workbench's repos.yaml (a lane run as
its own session). Everything else, the orchestrator and rspec's agents included, is not judged: under
`observe` the spec side is meant to read the reference.

WHAT IS DENIED. The holdout, `<workbench>/../<project>-holdout`, under every posture and whether or not
it exists yet. The reference checkout unless `sources.yaml` `reference.posture` is own-code (empty
means own-code for `reference.kind: own-code`, else observe; an unknown value counts as strict, the
narrower reading): `reference.checkout`, plus the fallbacks scripts/preflight.py would find that are
git repos. A fallback that is, or holds, a repo listed in repos.yaml is never denied, because
`../<reference.name>` can be the rebuild's own repo when the two share a name.

IT IS A GUARD, NOT A SANDBOX. Read, Grep and Glob are judged by their path fields, a Grep or Glob
whose search root holds a denied path included. Bash is judged by the directory each simple command
runs in (after `cd`), by every word that resolves to a path, and by any denied path spelled in the raw
text. A path the shell computes at run time (`$X`, `$(…)`), a script that opens the path itself, or a
tool other than these four is not seen. The README says so; the E2E runs check the guard's denials.

The deny message names no path: a lane reads it, and P4 says nothing a lane sees names the holdout.
Fails open outside a 3.x workbench; a crash inside a pipeline session blocks (guard_io).
"""

import os
import re
import sys

from guard_io import (
    read_payload, block_on_crash, tool_call, command_dir, command_walk, expand_home, emit_decision,
    real_path, utf8_stdio, UNKNOWN, CASE_INSENSITIVE_FS,
)
from hooklib import (
    get, read_text, session_root, workbenches_near, listed_repos, pipeline_repo_of, is_current_workbench, _native,
)

GUARD = "reference_guard"
LANE_AGENT = re.compile(r"(?:^|:)lane-worker\Z")
POSTURES = ("strict", "observe", "own-code")
GLOB_CHARS = re.compile(r"[*?\[{]")
DENY = ("Denied by product-rebuild's reference guard: a build lane may not read the reference product's code "
        "or the hidden tests. Build from your specs, the locked contracts and the open acceptance bundle; if they "
        "leave a behaviour unclear, raise it as a spec question instead of looking for the answer.")


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


def _project(wb):
    try:
        m = re.search(r"^project:[ \t]*(\S+)", read_text(os.path.join(wb, "locks", "pipeline.yaml")), re.M)
    except OSError:
        m = None
    name = m.group(1).strip("\"'") if m else os.path.basename(wb)
    return re.sub(r"-workbench\Z", "", name)


def denied_roots(wb):
    parent = os.path.dirname(wb)
    roots = [os.path.join(parent, f"{_project(wb)}-holdout")]
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


def _spellings(root):
    forward = root.replace("\\", "/")
    out = {root, forward}
    m = re.match(r"^([a-zA-Z]):/(.*)", forward)
    if m:
        out.add(f"/{m.group(1).lower()}/{m.group(2)}")
    return out


def bash_reaches(command, cwd, roots):
    for c in command_walk(command, cwd):
        d = c["dir"]
        if d and _inside(d, roots):
            return True
        words = list(c["argv"]) + [r.get("target") for r in c["redirects"] if isinstance(r.get("target"), str)]
        for w in words:
            if not isinstance(w, str) or not w or UNKNOWN in w:
                continue
            for cand in ([w.split("=", 1)[1]] if "=" in w else []) + ([] if w.startswith("-") else [w]):
                p = _resolve(cand, d or cwd)
                if p and _inside(p, roots):
                    return True
    # The raw text, for a spelling the tokenizer leaves unresolved (inside a quoted script, an
    # interpreter's -c). Only at a path boundary, so `.../ref` does not match `.../reference-notes`.
    flags = re.I if CASE_INSENSITIVE_FS else 0
    for r in roots:
        for s in _spellings(r):
            if re.search(re.escape(s) + r"(?=$|[\\/\s\"';|&)])", command, flags):
                return True
    return False


def tool_reaches(name, inp, cwd, roots):
    base = get(inp, "path")
    base = _resolve(base, cwd) if isinstance(base, str) and base else cwd
    if name == "Read":
        target = get(inp, "file_path")
        return isinstance(target, str) and bool(target) and _inside(_resolve(target, cwd), roots)
    if _inside(base, roots) or _holds(base, roots):
        return True
    pattern = get(inp, "pattern")
    if name == "Glob" and isinstance(pattern, str) and pattern:
        static = GLOB_CHARS.split(pattern, 1)[0]
        p = _resolve(static, base) if static else base
        return _inside(p, roots) or _holds(p, roots)
    return False


def main():
    utf8_stdio()
    data = read_payload(GUARD)
    block_on_crash(GUARD, data)
    call = tool_call(data)
    if call.name not in ("Read", "Grep", "Glob", "Bash") or not is_lane(data):
        return 0
    roots = [r for wb in workbenches_near(session_root(data)) if is_current_workbench(wb) for r in denied_roots(wb)]
    if not roots:
        return 0
    cwd = command_dir(data)
    if call.name == "Bash":
        command = get(call.input, "command")
        hit = isinstance(command, str) and bash_reaches(command, cwd, roots)
    else:
        hit = tool_reaches(call.name, call.input, cwd, roots)
    if hit:
        emit_decision("deny", DENY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
