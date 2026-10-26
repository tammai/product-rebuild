#!/usr/bin/env python3
"""runbook_guard.py — PreToolUse hook: block writes into a CODE REPO while a slice after S1
is in progress and the workbench has no plan/BUILD_RUNBOOK.md.
Reads the hook payload from stdin, finds the code repo root above the target file
(marker: .rebuild-workbench, holding the absolute workbench path), and denies the write.
Exit 0 = allow. Exit 2 = block (stderr is fed back to the model).
Fails open on anything unexpected — the guard must never break unrelated edits.

WHAT IT PROTECTS

S1 is where the team discovers how the locked contracts, the harness scaffold and the
reference's quirks actually combine — which codegen invocation works, which harness output
needed adjusting, what the running reference does that the spec never said. None of that is
written anywhere S2's agents will read, so every later slice's lanes rediscover it, each at
full price, each slightly differently.

The runbook is the fix, and this hook is why it gets written. The rule could have been a line
in g5-build.md telling the orchestrator to write it at the S1 boundary — but an instruction
the orchestrator applies to itself mid-slice is a budget, and a hook is a limit. That is the
same argument that made gate_guard a hook rather than a paragraph.

WHY THE MARKER, AND NOT THE SUBMODULE

A code repo pins the workbench as a read-only submodule at a GATE TAG — so the submodule's
own plan/progress.yaml is checked out at gate-4/vN and is stale by design: it cannot know
which slice is in progress, because slices happen after that tag. The guard needs the LIVE
workbench, so G5's repo checklist writes `.rebuild-workbench` at the repo root holding its
absolute path.

FAILING OPEN IS THE DEFAULT, AND IT IS DELIBERATE

No marker, an unreadable marker, a workbench path that no longer exists, no progress file,
no slice in progress, S1 in progress, a runbook already there — every one of those allows the
write. This guard fires on exactly one configuration. A guard that fires on anything it does
not understand blocks unrelated work in repos that have nothing to do with this pipeline, and
the escape hatch it offers has to be one that exists: here it is always "write the runbook",
a file the person being blocked can create in the next tool call.

Failing open on a missing marker has a cost: a repo created before the marker step existed had
this guard off for its whole life, and nothing said so. pause_check.py and lanes_check.py now
name any registered repo with no marker, or a wrong one, while a slice is in progress.
"""

import os
import re
import sys

from hooklib import read_payload, get, read_text, utf8_stdio


def main(argv=None):
    utf8_stdio()
    # Unlike the other guards this one does not use hooklib.locate(): the marker it walks up for
    # is a code repo's, not a workbench's, and the workbench is read from inside it.
    payload = read_payload()

    tool_input = get(payload, "tool_input")
    target = get(tool_input, "file_path") or get(tool_input, "path")
    if not target:
        return 0
    abs_ = os.path.abspath(os.path.join(get(payload, "cwd") or os.getcwd(), target))

    # Walk up for the code repo's marker.
    repo = os.path.dirname(abs_)
    while repo != os.path.dirname(repo):
        if os.path.exists(os.path.join(repo, ".rebuild-workbench")):
            break
        repo = os.path.dirname(repo)
    marker_path = os.path.join(repo, ".rebuild-workbench")
    if not os.path.exists(marker_path):
        return 0  # not a code repo of a rebuild project

    workbench = ""
    try:
        for line in (l.strip() for l in read_text(marker_path).split("\n")):
            if line and not line.startswith("#"):
                workbench = line
                break
    except Exception:
        return 0
    if not workbench:
        return 0
    # Relative is allowed and resolved against the repo root — a marker committed to a repo that
    # several people clone side by side with the workbench is more useful relative than absolute.
    wb_root = workbench if os.path.isabs(workbench) else os.path.abspath(os.path.join(repo, workbench))
    if not os.path.exists(os.path.join(wb_root, "locks", "pipeline.yaml")):
        return 0  # stale marker

    # Never guard the workbench itself. Writing the runbook is the remedy this hook names, and a
    # guard that blocked its own remedy would be the pre-0.14.0 flows-guard mistake again: an
    # escape hatch that does not exist.
    # `os.sep`, not "/": abspath() returns backslashes on Windows, where a "/" suffix never matched and
    # the guard blocked writing the runbook itself.
    if os.path.abspath(abs_) == os.path.abspath(wb_root) or os.path.abspath(abs_).startswith(os.path.abspath(wb_root) + os.sep):
        return 0

    runbook = os.path.join(wb_root, "plan", "BUILD_RUNBOOK.md")
    if os.path.exists(runbook):
        return 0  # the thing this guard exists to require

    # Which slice is in progress? Same fixed-YAML-subset read as gate.py's slice_states(): the
    # hook cannot depend on the workbench's vendored scripts, and this is one `slices:` block.
    progress_path = os.path.join(wb_root, "plan", "progress.yaml")
    if not os.path.exists(progress_path):
        return 0
    # CRLF to LF first (read_text does it): with core.autocrlf=true the `^slices:\n` header never
    # matches a CRLF file, and the guard fails open on every Windows checkout.
    try:
        progress = read_text(progress_path)
    except Exception:
        return 0
    block = re.search(r"^slices:\n((?:(?:[ \t]+.*)?\n)*)", progress, re.M)
    if not block:
        return 0
    in_progress = [m.group(1) for m in re.finditer(r"^\s+(S[0-9]+):\s*([a-z-]+)", block.group(1), re.M)
                   if m.group(2) == "in-progress"]
    if not in_progress:
        return 0

    # S1 is exempt, and it is the whole point: S1 is where the runbook's content is DISCOVERED.
    # Requiring it during S1 would require writing down lessons nobody has learned yet.
    after_s1 = [i for i in in_progress if i != "S1"]
    if not after_s1:
        return 0

    print(
        f"Blocked: {', '.join(after_s1)} {'are' if len(after_s1) > 1 else 'is'} in progress and "
        f"{runbook} does not exist.\n"
        f"\n"
        f"Slice S1 discovered how the locked contracts, the harness scaffold and the reference's "
        f"quirks actually combine. None of that is written anywhere this slice's lanes will read, so "
        f"they are about to rediscover it — each lane separately, and not necessarily the same way.\n"
        f"\n"
        f"Write the build runbook first, at the workbench, from what the S1 lanes REPORTED — not from "
        f"memory (g5-build.md, \"Write the build runbook\"). Fixed sections: how codegen from "
        f"contracts/ was invoked and what it got wrong; harness quirks that needed adjusting, and why; "
        f"reference behaviors the running instance revealed that the spec did not say; the "
        f"test-fixture approach; deploy prerequisites that turned out to be missing; commands that "
        f"worked, verbatim.\n"
        f"\n"
        f"  {runbook}\n"
        f"\n"
        f"Creating that file unblocks this write immediately — the guard checks only that it exists. "
        f"An empty one would satisfy the hook and defeat the point, which is why the sections are "
        f"named above and why slice_review.py asks, at every later boundary, what this slice taught "
        f"that the runbook did not know.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
