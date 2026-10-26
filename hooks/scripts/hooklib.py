#!/usr/bin/env python3
"""hooklib.py — shared prelude for the PreToolUse guards. Every guard reads the hook payload,
resolves the target file, and walks up to the workbench root (marker: locks/pipeline.yaml).
Each of those used to be copy-pasted; one copy to fix is the point of this file.
Every helper fails open: it exits 0 itself when the edit is not one the guards care about.

It is a library the guards import, not a hook of its own: a hook is one process per tool call,
and the guards need to agree on what a workbench and a listed repo are. Python port of lib.mjs;
if you change a rule here, the guards that import it change with it.
"""

import json
import os
import re
import sys


def utf8_stdio():
    """Make stdout and stderr UTF-8 with LF newlines.

    A guard prints JSON decisions and block messages that carry non-ASCII paths; on Windows the
    default is a legacy code page that raises on them, and text mode would turn LF into CRLF.
    A hook that crashed while printing its block message would exit 1, which Claude Code treats
    as "allow".
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        except Exception:
            pass


def read_text(path):
    """A file as text: UTF-8, CRLF and bare CR turned into LF.

    A lock or repos.yaml checked out with core.autocrlf=true carries CRLF, and a `^...$`
    pattern run over it never matches — which for a guard means every edit is let through.
    """
    with open(path, "rb") as f:
        return re.sub(r"\r\n?", "\n", f.read().decode("utf-8", errors="replace"))


def _reject_constant(name):
    # json accepts NaN/Infinity; JSON.parse does not, and a payload carrying them is malformed.
    raise ValueError(f"invalid JSON constant {name}")


def parse_json(text):
    """json.loads with JSON.parse's strictness (no NaN, Infinity or -Infinity)."""
    return json.loads(text, parse_constant=_reject_constant)


def read_stdin_text():
    # errors="replace" like Node's utf-8 decoding: invalid bytes become U+FFFD, they do not throw.
    return sys.stdin.buffer.read().decode("utf-8", errors="replace")


def read_payload():
    try:
        return parse_json(read_stdin_text())
    except Exception:
        sys.exit(0)


def get(obj, key):
    """obj[key] for a JSON object, None for anything else — JS's `obj?.key`, which is undefined
    on a string, number or array instead of raising."""
    return obj.get(key) if isinstance(obj, dict) else None


def truthy(value):
    """JS truthiness, for the `a || b` fallbacks: an empty array or object is truthy there."""
    if isinstance(value, (list, dict)):
        return True
    return bool(value)


def js_number(value):
    """Number(value) for a parsed-JSON value, NaN where JS gives NaN. null is 0, as in JS: a
    snapshot whose `used_percentage` is null reads as 0%, not as missing."""
    nan = float("nan")
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip(" \t\n\r\x0b\x0c\u00a0\u2028\u2029\ufeff")
        if s == "":
            return 0.0
        if re.fullmatch(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", s):
            return float(s)
        if re.fullmatch(r"[+-]?Infinity", s):
            return float(s.replace("Infinity", "inf"))
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", s):
            return float(int(s, 16))
        return nan
    return nan


def locate():
    """Returns (payload, abs, root), or exits 0 when there is no target or no workbench above it."""
    payload = read_payload()
    tool_input = get(payload, "tool_input")
    target = get(tool_input, "file_path") or get(tool_input, "path")
    if not target:
        sys.exit(0)
    abs_ = os.path.abspath(os.path.join(get(payload, "cwd") or os.getcwd(), target))
    root = os.path.dirname(abs_)
    while root != os.path.dirname(root):
        if os.path.exists(os.path.join(root, "locks", "pipeline.yaml")):
            break
        root = os.path.dirname(root)
    if not is_v1_workbench(root):
        sys.exit(0)  # not in a workbench, or in one a 0.x release made
    return payload, abs_, root


def parse_protects(text):
    """The paths a lock file protects: the `  - x` items of the top-level `protects:` block only,
    not any other indented list in the file (e.g. `history:` entries).
    CRLF is normalised here rather than at each caller: a lock file checked out with
    core.autocrlf=true never matches `^protects:[ \\t]*\\n`, and an empty list means gate_guard
    lets every edit through to a locked gate.
    """
    block = re.search(r"^protects:[ \t]*\n((?:[ \t]+.*\n?)*)", re.sub(r"\r\n?", "\n", text), re.M)
    if not block:
        return []
    return [m.group(1).strip() for m in re.finditer(r"^  - (.+)$", block.group(1), re.M)]


# --- Windows: paths written MSYS-style -------------------------------------------------------
# Takes `platform` and `home` as arguments rather than reading sys.platform, so
# eval/lane_guards.py can check the win32 branch on a POSIX host.

def native_path(p, platform, home=None):
    """A path as Python on this platform reads it. On win32 a Bash command written for Git Bash
    names directories MSYS-style (`cd /c/Users/x/app`), which `abspath()` turns into
    `C:\\c\\Users\\x\\app` — no repo there, so the guards judged a directory that does not exist
    and were skipped by spelling alone (issue #3 in 0.x). `/c/...` and `/cygdrive/c/...` become
    `C:/...`; `~` becomes the home directory, since HOME is often unset outside Git Bash. Other
    platforms get only the `~` expansion.
    """
    s = re.sub(r"^~(?=[\\/]|\Z)", lambda _m: home or "~", p, count=1)
    if platform == "win32":
        s = re.sub(r"^/(?:cygdrive/)?([a-zA-Z])(?:/|\Z)", lambda m: m.group(1).upper() + ":/", s, count=1)
    return s


# --- Which repos the guards judge ----------------------------------------------------------------
# WHY THE GUARDS NEED A SCOPE. Plugin hooks fire in every session where the plugin is enabled,
# including sessions that have nothing to do with a rebuild. A guard that blocked `git push -f`
# or a 30-line edit in an unrelated project would be a bug in this plugin, so every blocking
# guard judges only a repo the pipeline owns: one listed in the `repos.yaml` of a workbench at
# or near the session root. Anything else fails open (exit 0).
#
# WHERE A WORKBENCH IS LOOKED FOR: the session root, its direct children (the layout
# rebuild_init creates: <project>/<name>-workbench beside the code repos), and — when the
# session root is itself a git repo — its parent's direct children, which is where the workbench
# is for a session started inside a code repo. repos.yaml is read with the same fixed-subset
# regex as scripts/lanes_check.py and pause_check.py: copied, not imported, since a hook
# cannot depend on a workbench's vendored scripts. If you change one, change all three.
#
# Plugin hooks load wherever a session starts; a code repo's own `.claude/settings.json` does
# not (checked 2026-10-06: a nested repo's hook that blocked every Write was bypassed from a
# parent-rooted session and fired from inside the repo). That is the reason these guards are
# this plugin's hooks and not files written into each repo.

def _real(p):
    # fs.realpathSync throws on a path that does not exist, and the fallback was the unresolved
    # path; os.path.realpath would instead resolve the part that does exist. Kept as the JS did.
    try:
        if os.path.exists(p):
            return os.path.realpath(p)
    except OSError:
        pass
    return os.path.abspath(p)


def _native(p):
    return native_path(p, sys.platform, os.path.expanduser("~"))


def session_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or get(payload, "cwd") or os.getcwd()


def is_v1_workbench(d):
    """True for a workbench made by a 1.x release: locks/pipeline.yaml says `rebuild_major: 1` or more.

    The fence that keeps these guards off a 0.x workbench. A 0.x workbench has the same
    locks/pipeline.yaml marker and none of what 1.x's guards assume (a listed repo made by
    scaffold-repo, a lane PLAN.md written by lane_plan.py), so acting on it would block work the
    0.x pipeline permits. Without the key this reads as "not ours" and the caller fails open, the
    same rule every guard already follows for a missing workbench."""
    try:
        with open(os.path.join(d, "locks", "pipeline.yaml"), encoding="utf-8") as f:
            m = re.search(r"^rebuild_major:\s*([0-9]+)", f.read().replace("\r\n", "\n"), re.M)
    except OSError:
        return False
    return bool(m) and int(m.group(1)) >= 1


_is_workbench = is_v1_workbench


def _child_dirs(d):
    try:
        # A symlink to a directory is not a directory entry here, as with Dirent.isDirectory().
        with os.scandir(d) as it:
            return sorted(os.path.join(d, e.name) for e in it if e.is_dir(follow_symlinks=False))
    except OSError:
        return []  # unreadable root: no workbench found, so the caller fails open


def workbenches_near(root):
    found = {}

    def scan(d):
        if _is_workbench(d):
            found[d] = True
        for c in _child_dirs(d):
            if _is_workbench(c):
                found[c] = True

    scan(root)
    if os.path.exists(os.path.join(root, ".git")):
        for c in _child_dirs(os.path.dirname(root)):
            if _is_workbench(c):
                found[c] = True
    return list(found)


def in_pipeline_session(payload):
    """True when a workbench is at or near the session root: the question the session-level hooks
    (canary seed, injection scan) ask, since they judge a session, not a repo."""
    return len(workbenches_near(session_root(payload))) > 0


def listed_repos(workbenches):
    listed = set()
    for wb in workbenches:
        repos_file = os.path.join(wb, "repos.yaml")
        if not os.path.exists(repos_file):
            continue
        text = read_text(repos_file)
        for m in re.finditer(r"^\s*-\s*(?:name:\s*(\S+)\s*)?path:\s*(\S+)", text, re.M):
            p = _native(m.group(2))
            listed.add(_real(p if os.path.isabs(p) else os.path.abspath(os.path.join(wb, p))))
    return listed


def pipeline_repo_of(target, payload):
    """{"worktree", "mainRepo"} when `target` (a file or directory, which need not exist yet) lies
    in a git worktree whose main repo is listed for this session, else None. Walks up from the
    nearest directory that exists, because a Write may create several. `.git` is a directory in a
    main checkout and a `gitdir:` file in a linked worktree; reading it directly avoids spawning
    git on every tool call. A lane's worktree counts through its main repo.
    """
    if not target:
        return None
    d = os.path.abspath(os.path.join(get(payload, "cwd") or session_root(payload), _native(target)))
    while not os.path.exists(d) and d != os.path.dirname(d):
        d = os.path.dirname(d)
    worktree = None
    cur = d
    while cur != os.path.dirname(cur):
        if os.path.exists(os.path.join(cur, ".git")):
            worktree = cur
            break
        cur = os.path.dirname(cur)
    if not worktree:
        return None
    main_repo = worktree
    try:
        git_path = os.path.join(worktree, ".git")
        if os.path.isfile(git_path):
            with open(git_path, "rb") as f:
                head = f.read().decode("utf-8", errors="replace")
            g = re.search(r"^gitdir:\s*(.+)$", head, re.M)
            gitdir = g.group(1).strip() if g else None
            m = gitdir and re.match(
                r"^(.*)[\\/]\.git[\\/]worktrees[\\/][^\\/]+\Z",
                os.path.abspath(os.path.join(worktree, gitdir)),
            )
            if m:
                main_repo = m.group(1)
    except Exception:
        pass  # unreadable .git file: treat the worktree as its own repo
    listed = listed_repos(workbenches_near(session_root(payload)))
    if _real(main_repo) in listed or _real(worktree) in listed:
        return {"worktree": worktree, "mainRepo": main_repo}
    return None


# --- PLAN.md: the two lines the spec gate reads ---------------------------------------------------
# scripts/lane_plan.py writes `Status:` and `Branch:` for these patterns. It is vendored into
# each workbench and must run alone, so it carries its own copy of the format rather than
# importing this; eval/lane_plan.py imports both and fails if they stop agreeing. If you change
# a pattern here, change lane_plan.py's header and writer with it.
PLAN_STATUS = re.compile(r"^Status:\s*(\S+)", re.M)
PLAN_BRANCH = re.compile(r"^Branch:\s*(\S+)", re.M)
