#!/usr/bin/env python3
"""briefs.py — write the brief file an arm's agent is told to read, so every arm gets identical text.

  python3 briefs.py worker   <task> <arm A|B|C|D> <run-dir> <out.md>
  python3 briefs.py verifier <task> <run-dir> <base-sha> "<implementer's test result line>" <out.md>

The agent prompt in the transcript is one line ("read <file> and follow it"), so the eval's prompts
differ between arms only by the file's contents, and the contents differ only where the arms do.
Arm A appends a self-audit step to the worker brief; B, C and D use the plain worker brief, and what
differs for B and D happens after the worker reports (a fresh verifier; a deterministic check).
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..", ".."))


def body(agent):
    # Pinned copies, not agents/*.md: the live agent files change as the pipeline changes, and an
    # edit to one leaked a self-check line into every arm of the first pilot (all four arms read it).
    # worker_rules.md is lane-worker.md as released in 1.0.0 with the two sentences that name a
    # verifier removed, so no arm is told whether anything checks its work after it reports.
    name = {"lane-worker": "worker_rules.md", "lane-verifier": "verifier_rules.md"}[agent]
    return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), name)).read()


SELF_AUDIT = """
## Before you report: audit your own work

When every row is Done and your tests pass, stop and audit before reporting. Re-read the Spec in
PLAN.md one acceptance criterion at a time and compare each with your code and your tests, looking for
a criterion implemented slightly differently from what it says (a rounding mode, a boundary that is
inclusive or exclusive, an error message's exact text, an order of checks). Fix what you find, rerun
your tests, then report.
"""

if sys.argv[1] == "worker":
    task, arm, d, out = sys.argv[2:6]
    module = {"invoice": "invoice.py", "ratelimit": "ratelimit.py", "subscription": "subscription.py",
              "shipping": "shipping.py", "coupons": "coupons.py", "leave": "leave.py",
              "bundle": "shipping.py`, `coupons.py` and `leave.py"}[task]
    text = f"""{body('lane-worker')}
---

# Your lane

You are the implementer for one lane of an eval. Worktree: `{d}` (branch `slice`). Its `PLAN.md` is
your approved plan.

- Implement the spec in `PLAN.md`: write `{module}` at the worktree root. Python 3.9+, standard library only.
- Write your own tests in `tests/` with `unittest`. Run them with:
  `cd {d} && PYTHONPATH=. python3 -B -m unittest discover -s tests`
- Give every acceptance criterion at least one test, and put the criterion's rule id in the test's
  name in identifier form (for example `test_r_inv_001_subtotal`).
- Set a row's Status to `Done` and put its test's name in Notes when its test passes.
- Test cadence: run the tests you wrote for what you touched, nothing else.
- Work only inside the worktree. Do not look for or read any file outside it.
- Commit your work in the worktree when done, with a Conventional Commit subject.
{SELF_AUDIT if arm == 'A' else ''}
Report as the Output section says.
"""
    open(out, "w").write(text)
elif sys.argv[1] == "verifier":
    task, d, base, testline, out = sys.argv[2:7]
    text = f"""{body('lane-verifier')}
---

# Your handoff

PLAN: {d}/PLAN.md
Diff: git -C {d} diff {base}   (covers committed and uncommitted work; also read untracked files from git -C {d} status --porcelain)
Files: run git -C {d} diff --stat {base}
Implementer's test run: {testline}
Return only the verify-contract JSON.

The spec section of PLAN.md is a module spec approved in a rebuild workbench. Its acceptance criteria
are the task rows. A criterion with a rule id must match what the spec states exactly.
Work only inside {d}. Do not look for or read any file outside it.
"""
    open(out, "w").write(text)
