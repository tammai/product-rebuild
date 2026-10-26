#!/usr/bin/env python3
"""spec_gate_guard.py — PreToolUse(Write|Edit|MultiEdit|NotebookEdit): blocks a non-trivial edit
in a pipeline code repo until the worktree's PLAN.md says `Status: approved`, and blocks an
edit governed by a PLAN.md left over from a different branch. Asks before any edit to the
gates themselves, whatever its size.

WHY IT EXISTS. In the linear rebuild, 56 of the backend's 68 slice commits added over 20 lines
of non-test code and no PLAN.md ever existed: nothing tied a lane's diff to the slice spec the
user had approved. The approval already exists — you approve a slice's specs before any code —
and lane_plan.py carries it into PLAN.md at that moment, by script. This hook is what makes
the plan a precondition instead of a courtesy.

WHY A LANE CANNOT APPROVE ITSELF. `*.md` is exempt below, so nothing here stops a lane writing
`Status: approved` into its own PLAN.md. The protection is elsewhere: lane_plan.py records a
sha256 of the plan's `## Spec` section, and slice_review.py re-checks it at the slice
boundary, so the edit is visible there. The messages below tell a lane not to try it.

SCOPE. Only a repo listed in a workbench's repos.yaml is judged (hooklib pipeline_repo_of);
anything else exits 0, because this hook fires in every session the plugin is enabled in. The
plan and the branch are read from the edited file's own worktree, never the session's: a
parent-rooted session's cwd is no repo, and resolving against it once read another tree's plan.

Ported in 1.0.0 from the harness this plugin used to depend on (MIT, BigIn; see NOTICE.md),
keeping its four hardening rules. Exit 2 blocks. The Status:/Branch: patterns are hooklib's
PLAN_STATUS and PLAN_BRANCH, which lane_plan.py writes for.
"""

import json
import os
import re
import subprocess
import sys

from guard_io import (
    read_payload, block_on_crash, tool_call, string_field, is_write_shaped, emit_decision, real_path, worktree_root,
    repo_relative, is_gate_file, utf8_stdio, js_trim,
)
from hooklib import pipeline_repo_of, PLAN_STATUS, PLAN_BRANCH, get, read_text

_FLAGS = re.I | re.A

# Trivial paths never require an approved plan: tests (both directory-named and
# `*_test.dart`-named), docs, env examples, config files, and generated graph artifacts
# (graphify-out/ is committed by design, so the git-ignore check below can't cover it).
TRIVIAL_PATTERNS = [
    re.compile(r"(^|[/\\])tests?[/\\]", _FLAGS),
    # Dart/Flutter: `foo_test.dart`. Needed on its own for the same reason
    # bugfix-test-guard.mjs needs it — `integration_test/` is not `test/`, so the
    # directory rule above misses every flow test, and a flow test is never ≤20 lines.
    re.compile(r"_test\.dart\Z", re.A),
    re.compile(r"\.md\Z", _FLAGS),
    re.compile(r"\.env\.example\Z", _FLAGS),
    re.compile(r"(^|[/\\])graphify-out[/\\]", _FLAGS),
    re.compile(r"(^|[/\\])(\.eslintrc(\.\w+)?|eslint\.config\.\w+|\.prettierrc(\.\w+)?|prettier\.config\.\w+|tsconfig(\.\w+)?\.json|vite\.config\.\w+|vitest\.config\.\w+|nuxt\.config\.\w+|\.editorconfig|\.gitignore|\.npmrc)\Z", _FLAGS),
]

# Proxy for the skill's own "≤20 lines of logic" spec-gate exemption.
LINE_THRESHOLD = 20
INFINITY = float("inf")


def lines(text):
    # A non-string here is a malformed payload field: `.replace` on it threw in the original,
    # and the caller turns that into "unmeasurable", which blocks.
    if not isinstance(text, str):
        raise TypeError("not a string")
    return [] if text == "" else text.replace("\r\n", "\n").split("\n")


def line_distance(a, b, max_):
    """Insertions + deletions between two line lists (Myers' O(ND) diff), or Infinity once
    that passes `max_`. Bounded, so a whole-file Write costs O(N·max) and never O(N²)."""
    off = max_ + 1
    v = [0] * (2 * max_ + 3)
    for d in range(max_ + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[off + k - 1] < v[off + k + 1]):
                x = v[off + k + 1]
            else:
                x = v[off + k - 1] + 1
            y = x - k
            while x < len(a) and y < len(b) and a[x] == b[y]:
                x += 1
                y += 1
            v[off + k] = x
            if x >= len(a) and y >= len(b):
                return d
    return INFINITY


def rewrite_size(old_text, new_text):
    """A whole-file Write over an existing file is sized by what it changes, the way an Edit
    is: max(lines removed, lines added). Sizing it by the line-count difference let any
    file be replaced wholesale with an equally long one and counted as 0."""
    a = lines(old_text)
    b = lines(new_text)
    d = line_distance(a, b, 2 * LINE_THRESHOLD + 1)  # > 2·threshold means max(…) > threshold
    if d == INFINITY:
        return INFINITY
    common = (len(a) + len(b) - d) // 2
    return max(len(a) - common, len(b) - common)


def _read(path):
    # No CRLF normalisation: line counts are taken after lines() handles CRLF itself.
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def _prop(obj, name):
    """obj.name in JS: undefined on a string, number or array, a TypeError on null."""
    if obj is None:
        raise TypeError("cannot read properties of null")
    return obj.get(name) if isinstance(obj, dict) else None


def _or_empty(value):
    return "" if value is None else value


def notebook_size(tool_input, file_path):
    """A NotebookEdit is sized like an Edit of one cell: `insert` adds new_source, `delete`
    removes the cell, `replace` (the default) swaps the cell's source for new_source. The
    old source comes from the notebook itself; a cell we can't find counts as empty for an
    insert or replace, and as unmeasurable for a delete."""
    added = len(lines(_or_empty(get(tool_input, "new_source"))))
    edit_mode = get(tool_input, "edit_mode")
    if edit_mode == "insert":
        return added
    old = None
    try:
        cells = _prop(json.loads(_read(file_path)), "cells")
        cell = None
        if cells is not None:
            if not isinstance(cells, list):
                raise TypeError("cells.find is not a function")
            cell = next((c for c in cells if _prop(c, "id") == get(tool_input, "cell_id")), None)
        if cell is not None:
            source = _prop(cell, "source")
            if isinstance(source, list):
                old = "".join(str(x) for x in source)
            else:
                old = str(_or_empty(source))
    except Exception:
        pass  # no such notebook yet, or not JSON — nothing to compare against
    if edit_mode == "delete":
        return INFINITY if old is None else len(lines(old))
    return added if old is None else rewrite_size(old, get(tool_input, "new_source"))


def change_size(tool_input, file_path):
    """Keyed on payload shape, not tool name: an unrecognized tool name would otherwise fall
    through to Infinity and block a two-line edit. Unmeasurable input still returns
    Infinity — a change we can't size is one we don't wave through."""
    edits = get(tool_input, "edits")
    if isinstance(edits, list):
        return sum(
            max(len(lines(_or_empty(_prop(e, "old_string")))), len(lines(_or_empty(_prop(e, "new_string")))))
            for e in edits
        )
    old_string = get(tool_input, "old_string")
    new_string = get(tool_input, "new_string")
    if isinstance(old_string, str) or isinstance(new_string, str):
        return max(len(lines(_or_empty(old_string))), len(lines(_or_empty(new_string))))
    if isinstance(get(tool_input, "new_source"), str) or get(tool_input, "edit_mode") == "delete":
        return notebook_size(tool_input, file_path)
    content = get(tool_input, "content")
    if isinstance(content, str):
        if not os.path.exists(file_path):
            return len(lines(content))
        try:
            return rewrite_size(_read(file_path), content)
        except Exception:
            return INFINITY  # exists but unreadable — can't size it
    return INFINITY


def measured(tool_input, file_path):
    """A malformed `edits` entry must not crash to exit 1, which Claude Code treats as "allow"."""
    try:
        return change_size(tool_input, file_path)
    except Exception:
        return INFINITY


def main(argv=None):
    utf8_stdio()
    data = read_payload("spec_gate_guard.py")
    block_on_crash("spec_gate_guard.py", data)
    call = tool_call(data)
    tool_input = call.input
    # Any field this gate reads, present with the wrong type, fails closed (exit 2).
    # NotebookEdit names its target `notebook_path`, not `file_path`.
    file_path = string_field(tool_input, "file_path", "spec_gate_guard.py") \
        or string_field(tool_input, "notebook_path", "spec_gate_guard.py")
    for field in ["content", "old_string", "new_string", "new_source", "cell_id", "edit_mode"]:
        string_field(tool_input, field, "spec_gate_guard.py")

    if not file_path:
        return 0

    # Self-filter on shape as well as on the registered matcher, so a tool added later that carries
    # file content is gated without hooks.json being updated first.
    if not is_write_shaped(call):
        return 0

    if not pipeline_repo_of(file_path, data):
        return 0  # not a repo the pipeline owns

    # A hook's cwd is the session root, which is not the worktree the edited
    # file lives in. Resolving the plan and the branch against cwd reads another tree's
    # state — it blocked every non-trivial edit in a parallel-worktree run despite an
    # approved plan beside the file, and worse, let a main-worktree plan wave through an
    # edit in a worktree that had none. Both resolve against the target file's tree, found
    # from the nearest directory that exists (a Write may create several). Only a file in
    # no repository at all falls back to the session root.
    repo_root = worktree_root(file_path)
    root = repo_root if repo_root is not None else real_path(get(data, "cwd") or os.getcwd())

    # Every path rule below judges the real path relative to that root — never the raw
    # string, where `src/test/../app.ts` or a repo cloned under ~/tests/ matched "tests/".
    # A file outside the root is judged by its name alone.
    rel = repo_relative(file_path, root)

    # The gates' own inputs (is_gate_file() in guard_io.py). A one-line edit to a guard or its
    # registration turns a gate off for every later call — exactly what an injected
    # instruction would ask for — so the size threshold and an approved plan are both
    # beside the point: a person confirms.
    if is_gate_file(rel):
        emit_decision(
            "ask",
            f"{rel} is part of this repo's commit and edit gates — a change here can switch one off. Confirm this edit is one you asked for.",
        )
        return 0

    name = rel if rel is not None else os.path.basename(file_path)
    if any(p.search(name) for p in TRIVIAL_PATTERNS):
        return 0

    # Build output and local caches aren't reviewable source: a git-ignored path never
    # reaches the diff a plan is written against, so the gate has nothing to govern there.
    # Deliberately index-aware (no --no-index) — a *tracked* file that merely matches a
    # gitignore pattern is still gated, which is why graphify-out/ needs its rule above.
    # Asked of the file's own repo, not of whatever repo the hook happens to run in.
    def is_git_ignored():
        if not repo_root:
            return False
        try:
            r = subprocess.run(
                ["git", "-C", repo_root, "check-ignore", "-q", "--", real_path(file_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return r.returncode == 0
        except Exception:
            return False  # exit 1 = not ignored; 128 = unusable path

    if is_git_ignored():
        return 0

    def current_branch():
        try:
            r = subprocess.run(
                ["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
            )
            b = js_trim(r.stdout.decode("utf-8", errors="replace"))
            return None if b == "HEAD" else b  # detached HEAD — nothing to compare against
        except Exception:
            return None  # not a git repo, or git unavailable

    def plan_verdict():
        """{ok: True} | {ok: False, status} | {ok: False, declared, actual} for a branch mismatch.
        `status` is None for a missing plan or one with no Status: line."""
        plan_path = os.path.join(root, "PLAN.md")
        if not os.path.exists(plan_path):
            return {"ok": False, "status": None}
        plan = read_text(plan_path)
        status = PLAN_STATUS.search(plan)
        if not status or status.group(1).lower() != "approved":
            return {"ok": False, "status": status.group(1).lower() if status else None}

        # `Branch:` is optional — plans written before it existed, or on a detached HEAD,
        # simply skip the check. Never block on something git can't answer.
        m = PLAN_BRANCH.search(plan)
        declared = m.group(1) if m else None
        if not declared:
            return {"ok": True}
        actual = current_branch()
        if not actual or declared == actual:
            return {"ok": True}
        return {"ok": False, "declared": declared, "actual": actual}

    verdict = plan_verdict()
    if verdict["ok"]:
        return 0

    if measured(tool_input, file_path) > LINE_THRESHOLD:
        def refuse(text):
            print(text, file=sys.stderr)
            sys.exit(2)

        if verdict.get("declared"):
            refuse(f"Error: PLAN.md is for branch '{verdict['declared']}' but HEAD is '{verdict['actual']}' — a leftover plan from another lane, or the wrong worktree. Do not edit PLAN.md's Branch: line; report it to the orchestrator.")
        if verdict.get("status") == "amending":
            refuse("Error: PLAN.md is Status: amending — the approved spec was found wrong, so non-trivial edits are frozen until the orchestrator re-approves it. Stop and report what is wrong; do not edit around the freeze.")
        refuse("Error: PLAN.md missing or not approved. A lane's PLAN.md is written by the orchestrator (lane_plan.py) from the slice specs the user approved. Never write or approve your own. Report it to the orchestrator, or keep the change ≤20 lines.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
