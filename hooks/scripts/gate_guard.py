#!/usr/bin/env python3
"""gate_guard.py — PreToolUse hook: block edits to files protected by a LOCKED gate.
Reads the hook payload from stdin, finds the nearest workbench root above the target
file (marker: locks/pipeline.yaml), and denies writes into locked `protects:` paths.
Exit 0 = allow. Exit 2 = block (stderr is fed back to the model).
Fails open on anything unexpected — the guard must never break unrelated edits.

It is a hook and not a line in a brief because a lane that has just been told a gate is locked
is the lane most likely to want to edit past it; the instruction does not stop the write, the
hook does.
"""

import os
import re
import sys

from hooklib import locate, parse_protects, read_text, utf8_stdio


def main(argv=None):
    utf8_stdio()
    _payload, abs_, root = locate()

    rel = "/".join(os.path.relpath(abs_, root).split(os.sep))
    for g in range(1, 6):
        lock_path = os.path.join(root, "locks", f"gate-{g}.yaml")
        if not os.path.exists(lock_path):
            continue
        # CRLF-normalised: `^status: locked$` never matches a CRLF lock file, and a guard that
        # cannot see the lock lets every edit through to a locked gate.
        text = read_text(lock_path)
        if not re.search(r"^status: locked$", text, re.M):
            continue
        protects = parse_protects(text)
        for p in protects:
            norm = re.sub(r"/\Z", "", p, count=1)
            if rel == norm or rel.startswith(norm + "/"):
                print(
                    f"Blocked: {rel} is protected by gate-{g} (status: locked). "
                    f"Do not edit locked artifacts. If this change is genuinely needed, propose "
                    f"reopening the gate to the user: python3 scripts/gate.py reopen gate-{g} --reason \"...\"",
                    file=sys.stderr,
                )
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
