#!/usr/bin/env python3
"""_run_all.py: runs every eval in this folder (or the folder given) and ends with one TAP line per failing check.

  python3 skills/rebuild-pipeline/eval/_run_all.py [folder]

WHY IT EXISTS. The evals are plain scripts that print `FAIL  <check>`, which sdlc's `ship.py --waive-baseline` cannot
read: it matches failures to .sdlc/baseline.md only from runner output it knows. So a change whose only failures
were the baselined ones could not ship. This is `.sdlc/config.json`'s `test` command, and ends the run with
`not ok N - <file> › <check>` per failure and `# fail N` (TAP, the one format ship.py reads whole: its pytest
pattern stops at the first space, and every check here has spaces). ship.py strips `<file> › ` to match the
baseline's `eval/<file> › <check>` cells.

A file whose name starts with `_` is a helper, not an eval: this one is, so it never runs itself.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

FAIL = re.compile(r"^FAIL\s+(.+?)\s*$", re.M)


def main(argv):
    folder = argv[0] if argv else os.path.dirname(os.path.abspath(__file__))
    evals = [p for p in sorted(glob.glob(os.path.join(folder, "*.py"))) if not os.path.basename(p).startswith("_")]
    failed, worst = [], 0
    for path in evals:
        name = os.path.basename(path)
        print(f"\n### {name}", flush=True)
        r = subprocess.run([sys.executable, path], capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        sys.stdout.write(out)
        sys.stdout.flush()
        checks = FAIL.findall(out)
        failed += [f"{name} › {c}" for c in checks]
        # A crash before any check, or a failure the eval only reports through its exit code, still counts.
        if r.returncode and not checks:
            failed.append(f"{name} › exited {r.returncode} with no FAIL line")
        worst = max(worst, r.returncode)
    print()
    for n, f in enumerate(failed, 1):
        print(f"not ok {n} - {f}")
    print(f"# fail {len(failed)}")
    return worst or (1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
