#!/usr/bin/env python3
"""commit_gates.py — PreToolUse(Bash): two checks on a `git commit` before it runs.
  1. The subject is a Conventional Commit (commit_rules.py).
  2. A fix-shaped commit includes a test file: every bug fix ships a regression test.

WHY BOTH ARE HERE. The second depends on the first: "is this a fix?" is read off the `fix:`
prefix, so a lane that writes `Fixed the bug` is not a fix commit and escapes the test rule.
Checking the subject first makes the type reliable. The git `commit-msg` hook checks the
subject too (for commits made outside Claude); only a Claude-side hook can see the staged
files at the moment a lane commits, which is where the regression-test rule is enforced.

SCOPE. Each `git commit` is judged by the directory it runs in, and ignored unless that is a
repo listed in a workbench's repos.yaml (hooklib pipeline_repo_of). Such a repo is also trusted
as a place to run git, whichever directory the session started in.

Ported in 1.0.0 from the harness this plugin used to depend on (MIT, BigIn; see NOTICE.md).
Self-filtering: anything but `git commit` exits 0. Exit 2 blocks.
"""

import os
import re
import sys

from guard_io import (
    read_payload, block_on_crash, tool_call, string_field, command_dir, project_dir, git_invocations, commit_message,
    parse_options, is_long, COMMIT_GRAMMAR, safe_git, real_path, repo_relative, utf8_stdio, js_trim, JS_SPACE,
)
from hooklib import pipeline_repo_of
from commit_rules import subject_problem

_FLAGS = re.I | re.A

TEST_PATTERNS = [
    re.compile(r"\.test\.[^/\\]+\Z", _FLAGS),
    re.compile(r"\.spec\.[^/\\]+\Z", _FLAGS),
    re.compile(r"_test\.go\Z", re.A),
    # Dart/Flutter: `foo_test.dart`. Needed on its own because `integration_test/` is not
    # `test/` — without this a bug fix shipping an integration test is blocked for having no test.
    re.compile(r"_test\.dart\Z", re.A),
    re.compile(r"(^|[/\\])tests?[/\\]", _FLAGS),
    re.compile(r"(^|[/\\])__tests__[/\\]", re.A),
]

# Docs/config-only fixes have no runtime surface to test — same allowlist as
# spec_gate_guard.py (minus its git-ignore check: staged files are tracked by definition).
# If you change one, change both.
TRIVIAL_PATTERNS = [
    re.compile(r"\.md\Z", _FLAGS),
    re.compile(r"\.env\.example\Z", _FLAGS),
    re.compile(r"(^|[/\\])graphify-out[/\\]", _FLAGS),
    re.compile(r"(^|[/\\])(\.eslintrc(\.\w+)?|eslint\.config\.\w+|\.prettierrc(\.\w+)?|prettier\.config\.\w+|tsconfig(\.\w+)?\.json|vite\.config\.\w+|vitest\.config\.\w+|nuxt\.config\.\w+|\.editorconfig|\.gitignore|\.npmrc)\Z", _FLAGS),
]

# JS `^` under the m flag also follows \r,   and  , which a pasted message can carry.
_LINE_START = r"(?:\A|(?<=[\n\r  ]))"
FIX_PREFIX = re.compile(_LINE_START + JS_SPACE + r"*fix(\([^)]*\))?!?:", _FLAGS)
BUGFIX_WORD = re.compile(r"\b(bugfix|hotfix)\b", _FLAGS)


def trusted_roots(data):
    """Where this guard will run git: the project and its own worktrees, nowhere else. The
    commit under judgement picks its directory, and a directory picks the config git
    loads — so a `-C` or `--git-dir` aimed outside the project is not followed."""
    root = real_path(project_dir(data))
    roots = [root]
    try:
        for line in safe_git(["worktree", "list", "--porcelain"], root).split("\n"):
            if line.startswith("worktree "):
                roots.append(real_path(line[9:]))
    except Exception:
        pass  # not a repo — the project root alone
    return roots


def inside(path, roots):
    real = real_path(path)
    return any(real == r or repo_relative(real, r) is not None for r in roots)


def files_for(inv, all_, pathspecs, data):
    """Files this commit will include: staged, tracked-modified when -a/--all is used, and any
    pathspec named on the command line. Read from the commit's own tree (after a `cd`, its
    -C, its --git-dir/--work-tree) — not from the hook's cwd, which in a parallel-worktree
    run is another tree's (empty) index. Never with the command's own VAR= prefixes or
    config: safe_git() drops GIT_* and pins core.fsmonitor off, because an env prefix that
    sets core.fsmonitor runs code in whatever git process reads that repo. None = not judged."""
    if inv["dir"] is None:
        return None
    roots = trusted_roots(data)
    places = [inv["dir"], *[os.path.abspath(os.path.join(inv["dir"], l[l.index("=") + 1:])) for l in inv["locator"]]]
    if not all(inside(p, roots) or pipeline_repo_of(p, data) for p in places):
        return None

    def git(args):
        return safe_git([*inv["locator"], *args, "--no-ext-diff", "--no-textconv"], inv["dir"]).split("\n")

    files = git(["diff", "--cached", "--name-only"])
    if all_:
        files = files + git(["diff", "--name-only"])
    return [f for f in (js_trim(f) for f in files + list(pathspecs)) if f]


def needs_test(inv, data):
    """False, True, or 'unknown' (a fix commit in a directory the shell computes)."""
    # No parsable message (editor, --no-edit, a message built by a command) → can't judge → allow.
    message = commit_message(inv)
    if message is None:
        return False

    # Explicit override: [no-test] in the message (state the reason next to it).
    if "[no-test]" in message:
        return False

    # Fix-shaped: conventional-commit fix prefix (any line), or bugfix/hotfix anywhere.
    if not FIX_PREFIX.search(message) and not BUGFIX_WORD.search(message):
        return False

    # A fix commit in a directory the shell computes (cd $X) has no index we can name.
    # That is the one fix-shaped case judged unknowable on purpose — it blocks.
    if inv["dir"] is None:
        return "unknown"

    opts, positionals = parse_options(inv["args"], **COMMIT_GRAMMAR)
    all_ = any(name == "-a" or is_long(name, "--all") for name, _ in opts)
    try:
        files = files_for(inv, all_, positionals, data)
    except Exception:
        return False  # not a git repo / git unavailable — never block on guard failure
    if files is None or len(files) == 0:
        return False
    if any(any(p.search(f) for p in TEST_PATTERNS) for f in files):
        return False
    if all(any(p.search(f) for p in TRIVIAL_PATTERNS) for f in files):
        return False
    return True


def first_line(message):
    if message is None:
        return None
    return next((l for l in (js_trim(x) for x in message.split("\n")) if l), None)


def main(argv=None):
    utf8_stdio()
    data = read_payload("commit_gates.py")
    block_on_crash("commit_gates.py", data)
    command = string_field(tool_call(data).input, "command", "commit_gates.py")

    # Every `git commit` the command would run, tokenized the way bash_guard.py does it — so
    # `git -C <dir> commit`, `-m"msg"` and a heredoc message are all seen. Each carries the
    # directory it runs in (after any `cd` and its own -C), which is whose index it commits.
    try:
        commits = [
            inv for inv in git_invocations(command, cwd=command_dir(data))
            if inv["sub"] == "commit" and pipeline_repo_of(inv["dir"] if inv["dir"] is not None else command_dir(data), data)
        ]
    except Exception:
        return 0  # can't parse it → can't judge; bash_guard.py blocks on the same input in a pipeline session

    # The subject first: the fix test below reads the type off it.
    for inv in commits:
        problem = subject_problem(first_line(commit_message(inv)))
        if problem:
            print(problem, file=sys.stderr)
            return 2

    verdicts = [needs_test(inv, data) for inv in commits]
    if "unknown" in verdicts:
        print("Error: fix commit in a directory this guard cannot resolve (a cd or -C target the shell computes). Write the directory literally so the regression-test check can read its staged files.", file=sys.stderr)
        return 2
    if True in verdicts:
        print(
            "Error: fix commit with no test file included. Every bug fix ships a regression test. Stage a test covering the bug, or add [no-test] to the commit message with the reason.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
