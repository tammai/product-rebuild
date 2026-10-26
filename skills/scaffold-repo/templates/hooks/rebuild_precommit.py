#!/usr/bin/env python3
"""rebuild_precommit.py — the git pre-commit gate: lint, type-check and the fast tests for each
package that has staged changes, using the commands in .rebuild/commands.json.

WHY IT RUNS WHAT IT RUNS. A pre-commit hook that runs the whole test suite makes every commit a
wait, and the suite is exactly what the slice's cadence says to run once, at the joint run. So
this runs `lint`, `typecheck` and `test_fast` (the stack's quick tests, when the manifest defines
one) and nothing slower. Build and the full `test` belong to CI and the joint run.

WHY IT FAILS OPEN WITHOUT commands.json. The hook is installed by the scaffold, before the
commands step has finished; a hook that blocks every commit of the skeleton itself would be
disabled by hand on day one, which is worse than a gate that opens until the commands exist.
Exit 1 blocks the commit.
"""
import json
import os
import subprocess
import sys


def main() -> int:
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    path = os.path.join(root, ".rebuild", "commands.json")
    if not os.path.exists(path):
        print("pre-commit: .rebuild/commands.json not written yet, so nothing to run.")
        return 0
    with open(path, encoding="utf-8") as f:
        packages = json.load(f)["packages"]
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=root, capture_output=True, text=True).stdout.split()
    for pkg in packages:
        prefix = "" if pkg["path"] == "." else pkg["path"].rstrip("/") + "/"
        if not any(s.startswith(prefix) for s in staged):
            continue
        for key in ("lint", "typecheck", "test_fast"):
            cmd = pkg["commands"].get(key)
            if not cmd:
                continue
            print(f"pre-commit [{pkg['name']}] {key}: {cmd}")
            if subprocess.run(cmd, cwd=os.path.join(root, pkg["path"]), shell=True).returncode != 0:
                print(f"pre-commit: {pkg['name']} {key} failed. Fix it; do not bypass the hook.", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
