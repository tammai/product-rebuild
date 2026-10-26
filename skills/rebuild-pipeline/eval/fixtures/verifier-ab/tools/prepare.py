#!/usr/bin/env python3
"""prepare.py — make one run directory for an arm: a git repo holding PLAN.md and an empty tests/.

  python3 prepare.py <task> <dest>

PLAN.md has the same shape lane_plan.py writes (`Status: approved`, `## Spec`, one task row per
acceptance criterion with its rule id), so the implementer meets the format it meets in a real lane.
The hidden tests are never copied in.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
task, dest = sys.argv[1], os.path.abspath(sys.argv[2])
spec = open(os.path.join(HERE, "..", "tasks", task, "spec.md")).read()
rows = re.findall(r"^(\d+)\. (\[R-[A-Z]+-\d+\].*(?:\n   .*)*)", spec, re.M)
os.makedirs(os.path.join(dest, "tests"), exist_ok=True)
open(os.path.join(dest, "tests", ".gitkeep"), "w").close()
open(os.path.join(dest, ".gitignore"), "w").write("__pycache__/\n*.pyc\n")
plan = ["# PLAN", "", "Status: approved", f"Branch: slice/S1-{task}", "Approved: eval fixture", "",
        "## Spec", "", spec.replace("\n## ", "\n#### ").replace("\n# ", "\n### ", 1) if spec.startswith("\n") else
        re.sub(r"^#{1,2} ", "#### ", spec, flags=re.M), "", "## Tasks", "",
        "| # | Task | Status | Notes |", "|---|------|--------|-------|"]
for n, text in rows:
    plan.append(f"| {n} | {' '.join(text.split())} | Todo | |")
open(os.path.join(dest, "PLAN.md"), "w").write("\n".join(plan) + "\n")
for cmd in (["git", "init", "-q", "-b", "slice"], ["git", "add", "-A"],
            ["git", "-c", "user.name=eval", "-c", "user.email=e@x", "commit", "-qm", "plan"]):
    subprocess.run(cmd, cwd=dest, check=True)
print(dest)
