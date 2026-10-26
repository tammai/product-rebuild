#!/usr/bin/env python3
"""cite_excerpts.py (eval) — does the citation file show the cited line, and name the ones it cannot open?

  python3 skills/rebuild-pipeline/eval/cite_excerpts.py

Builds a small git repo as the reference and a workbench whose findings and Rule Cards cite it, then asserts: a
transcribed citation shows the cited line, marked, with its neighbours; `observed` and `inferred` evidence is not
opened (the judge cannot re-derive those by design); a bad line, a missing path and an unknown commit are each
marked COULD NOT OPEN and make the script exit 2; and a missing checkout is refused.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

SCRIPTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "scripts")
failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


def sh(cwd, *cmd):
    return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


base = tempfile.mkdtemp(prefix="cite-eval-")
ref = os.path.join(base, "ref")
os.makedirs(os.path.join(ref, "app"))
with open(os.path.join(ref, "app", "total.rb"), "w") as f:
    f.write("\n".join(f"line {i}" if i != 7 else "total = qty * price # half-even" for i in range(1, 13)) + "\n")
sh(ref, "git", "init", "-q", "-b", "main")
sh(ref, "git", "add", "-A")
sh(ref, "git", "-c", "user.email=e@x", "-c", "user.name=e", "commit", "-qm", "ref")
commit = sh(ref, "git", "rev-parse", "HEAD")

subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "ce", "--dir", base],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
wb = os.path.join(base, "ce-workbench")
os.makedirs(os.path.join(wb, "findings", "rules"), exist_ok=True)


def ev(basis, path="app/total.rb", c=commit, line=7):
    d = {"path": path, "commit": c, "basis": basis}
    if line:
        d["line"] = line
    return d


def card(i, then, evidence):
    return {"id": i, "kind": "calculation", "given": "g", "then": then, "evidence": evidence, "features": [], "confidence": "high"}


def w(rel, obj):
    with open(os.path.join(wb, rel), "w") as f:
        f.write(json.dumps(obj))


w("findings/rules/billing.yaml", [
    card("R-BILL-001", "Totals round half-even.", [ev("transcribed")]),
    card("R-BILL-002", "Observed only.", [ev("observed")]),
    card("R-BILL-003", "Inferred only.", [ev("inferred")]),
])


def run(*a):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "cite_excerpts.py"), *a], cwd=wb, capture_output=True, text=True,
                          encoding="utf-8")


r = run("--checkout", ref)
check("a transcribed citation shows its line, marked, with neighbours",
      r.returncode == 0 and re.search(r">\s+7\s+total = qty \* price # half-even", r.stdout) and re.search(r"\s+4\s+line 4", r.stdout)
      and re.search(r"\s+10\s+line 10", r.stdout) and "Claim: Totals round half-even." in r.stdout, r.stdout + r.stderr)
check("observed and inferred evidence is not opened", "R-BILL-002" not in r.stdout and "R-BILL-003" not in r.stdout)
check("it reports how many it opened", "(1 transcribed citation(s), 1 opened, 0 could not be opened.)" in r.stdout, r.stdout[-200:])
w("findings/rules/billing.yaml", [
    card("R-BILL-001", "ok", [ev("transcribed")]),
    card("R-BILL-004", "bad line", [ev("transcribed", line=999)]),
    card("R-BILL-005", "bad path", [ev("transcribed", path="app/nope.rb")]),
    card("R-BILL-006", "bad commit", [ev("transcribed", c="0" * 40)]),
])
r = run("--checkout", ref)
check("a bad line, path and commit are each marked COULD NOT OPEN, and the call exits 2",
      r.returncode == 2 and len(re.findall(r"^COULD NOT OPEN:", r.stdout, re.M)) == 3 and "(4 transcribed citation(s), 1 opened, 3 could not be opened.)" in r.stdout,
      r.stdout[-700:])
check("a missing checkout is refused", run().returncode == 1 and run("--checkout", os.path.join(base, "nope")).returncode == 1)
with open(os.path.join(wb, "sources.yaml"), "w") as f:
    f.write(f"reference:\n  checkout: {ref}   # local clone\n")
check("the checkout is read from sources.yaml", run("--domain", "billing").returncode == 2)
o = run("--checkout", ref, "--out", "plan/gate-reviews/gate-1-citations.md")
check("--out writes the file", os.path.exists(os.path.join(wb, "plan/gate-reviews/gate-1-citations.md")), o.stdout + o.stderr)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
