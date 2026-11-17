#!/usr/bin/env python3
"""run_all_eval.py (eval): the suite runner names every failing check in a shape sdlc's ship.py can read.

  python3 skills/rebuild-pipeline/eval/run_all_eval.py

WHY IT EXISTS. Each eval prints its own `FAIL  <check>` lines, which sdlc 3.10's `ship.py --waive-baseline` cannot
parse, so a change whose only failures are the ones .sdlc/baseline.md lists could not ship. _run_all.py ends the run
with one TAP line per failing check and a `# fail N` count; this runs it over a folder of stand-in evals.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
base = tempfile.mkdtemp(prefix="run-all-eval-")
failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


def w(name, text):
    with open(os.path.join(base, name), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


w("a_pass.py", "print('ok    fine')\n")
w("b_fail.py", "import sys\nprint('FAIL  a check with spaces in it')\nprint('      detail')\n"
               "print('PASS  another')\nprint('FAIL  a second one')\nsys.exit(1)\n")
w("c_crash.py", "raise SystemExit(3)\n")
w("_helper.py", "raise SystemExit('a helper is not an eval')\n")
r = subprocess.run([sys.executable, os.path.join(HERE, "_run_all.py"), base], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
out = r.stdout + r.stderr
check("each failing check gets a TAP line naming its file and check, and the run counts them",
      "not ok 1 - b_fail.py › a check with spaces in it\n" in out and "not ok 2 - b_fail.py › a second one\n" in out
      and "# fail 3\n" in out, out)
check("an eval that exits non-zero with no FAIL line is still named, and the run exits non-zero",
      "not ok 3 - c_crash.py › exited 3 with no FAIL line\n" in out and r.returncode != 0
      and "a helper is not an eval" not in out, out)

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
