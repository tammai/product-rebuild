#!/usr/bin/env python3
"""check_plan.py — arm D's deterministic check: no model reads the code.

  python3 check_plan.py <run-dir>      # exit 0 clean, 1 with the problems listed

It asks three things a verifier would otherwise be asked in prose: does every PLAN.md row say Done
with a test named in Notes, does every row's rule id appear in a test (as `R-XXX-001` or the
identifier form `r_xxx_001`), and is the lane's own suite green. It cannot tell whether a test
asserts the right value, which is exactly what the comparison with the LLM verifier measures.
"""
import os
import re
import subprocess
import sys

d = os.path.abspath(sys.argv[1])
plan = open(os.path.join(d, "PLAN.md")).read()
problems = []
rows = re.findall(r"^\|\s*(\d+)\s*\|(.*?)\|\s*(\w+)\s*\|(.*?)\|\s*$", plan, re.M)
tests_src = ""
tdir = os.path.join(d, "tests")
for f in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
    if f.endswith(".py"):
        tests_src += open(os.path.join(tdir, f)).read() + "\n"
if not rows:
    problems.append("PLAN.md has no task rows")
for n, task, status, notes in rows:
    if status != "Done":
        problems.append(f"row {n} is {status}, not Done")
    if not notes.strip():
        problems.append(f"row {n} has no test named in Notes")
    m = re.search(r"\[(R-[A-Z]+-\d+)\]", task)
    if m and m.group(1) not in tests_src and m.group(1).lower().replace("-", "_") not in tests_src.lower():
        problems.append(f"row {n}: rule id {m.group(1)} appears in no test")
env = dict(os.environ, PYTHONPATH=d)
p = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"], cwd=d, env=env,
                   capture_output=True, text=True, timeout=120)
if p.returncode != 0:
    problems.append("the lane's own tests fail:\n" + (p.stderr or p.stdout)[-1200:])
print("\n".join(problems) if problems else "clean")
sys.exit(1 if problems else 0)
