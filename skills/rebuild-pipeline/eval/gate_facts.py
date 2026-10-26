#!/usr/bin/env python3
"""gate_facts.py (eval) — are the rubric's counts right, in both directions, and style-insensitive?

  python3 skills/rebuild-pipeline/eval/gate_facts.py
"""
from __future__ import annotations

import json
import os
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


base = tempfile.mkdtemp(prefix="gate-facts-eval-")
subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "gf", "--dir", base],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
wb = os.path.join(base, "gf-workbench")


def w(rel, text):
    p = os.path.join(wb, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


feats = [
    {"id": "F-A-001", "name": "a", "domain": "billing", "ground_truth": {"entities": ["work package", "Invoice"]}},
    {"id": "F-A-002", "name": "b", "domain": "billing", "ground_truth": {"entities": ["Ghost"]}},
    {"id": "F-B-001", "name": "c", "domain": "users", "ground_truth": {"entities": ["USER"]}},
]
w("matrix/features.yaml", json.dumps(feats))
w("findings/ground-truth/reference-erd.mermaid",
  'erDiagram\n  WORK_PACKAGE {\n    int id\n  }\n  INVOICE {\n    int id\n  }\n  USER ||--o{ INVOICE : places\n  LEDGER {\n    int id\n  }\n')
w("plan/slices.yaml", json.dumps([{"id": "S1", "name": "One", "features": ["F-A-001"]},
                                  {"id": "S2", "name": "Two", "features": ["F-A-002", "F-B-001", "F-B-002", "F-B-003"]}]))


def run(*a):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "gate_facts.py"), *a], cwd=wb, capture_output=True, text=True,
                          encoding="utf-8")


r = run("gate-1")
check("it runs", r.returncode == 0, r.stderr)
check("counts per domain and the spread", "- billing: 2" in r.stdout and "- users: 1" in r.stdout and "ratio 2.0x" in r.stdout, r.stdout)
check("an ERD entity no feature names is listed (LEDGER), and style differences are not orphans (work package, WORK_PACKAGE)",
      "named by no feature (1): LEDGER" in r.stdout, r.stdout)
check("a feature's entity the ERD lacks is listed with its feature (GHOST, F-A-002)", "- GHOST: F-A-002" in r.stdout, r.stdout)
r2 = run("gate-2")
check("slice counts and spread", "- S1 (One): 1" in r2.stdout and "- S2 (Two): 4" in r2.stdout and "ratio 4.0x" in r2.stdout, r2.stdout)
check("another gate is refused", run("gate-3").returncode == 1)
os.remove(os.path.join(wb, "findings/ground-truth/reference-erd.mermaid"))
check("no ERD says so instead of failing", "were not compared" in run("gate-1").stdout)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
