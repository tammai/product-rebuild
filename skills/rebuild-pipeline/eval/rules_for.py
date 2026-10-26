#!/usr/bin/env python3
"""rules_for.py (eval) — does the Rule Card filter keep every card reachable and never leave one out?

  python3 skills/rebuild-pipeline/eval/rules_for.py

The failure it guards is silent: a spec-writer that is handed too few cards writes a spec that never
mentions the missing rule, and nothing downstream can see an absence. So this asserts, on a workbench with
two domains, that (1) every card in every domain is either in full or an index line with its id, (2) a card
naming the module's feature is in full, (3) an invariant on an entity the module writes is in full even
though no feature names it, (4) an invariant on another entity is only indexed, (5) the header says how many
cards were filtered, and (6) with no features given the script refuses rather than returning nothing.
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


base = tempfile.mkdtemp(prefix="rules-for-eval-")
subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "rf", "--dir", base],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
wb = os.path.join(base, "rf-workbench")


def card(i, kind, features, entities, then):
    return {"id": i, "kind": kind, "given": "g", "then": then, "evidence": [], "features": features,
            "entities": entities, "confidence": "high"}


def w_cards(domain, cards):
    os.makedirs(os.path.join(wb, "findings", "rules"), exist_ok=True)
    with open(os.path.join(wb, "findings", "rules", f"{domain}.yaml"), "w", encoding="utf-8") as f:
        f.write(json.dumps(cards))  # JSON is YAML


w_cards("billing", [
    card("R-BILL-001", "calculation", ["F-BILL-001"], ["invoice"], "Totals round half-even to 2 dp."),
    card("R-BILL-002", "validation", ["F-BILL-002"], ["invoice"], "A negative amount is rejected with 422 " + "x" * 200),
    card("R-BILL-003", "invariant", [], ["invoice"], "An invoice's total equals the sum of its lines."),
    card("R-BILL-004", "invariant", [], ["ledger"], "The ledger always balances."),
    card("R-BILL-005", "state-transition", ["F-BILL-009"], ["subscription"], "A cancelled subscription cannot renew."),
])
w_cards("users", [card("R-USER-001", "validation", ["F-USER-001"], ["user"], "Emails are unique.")])


def run(*a):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "rules_for.py"), *a], cwd=wb, capture_output=True,
                          text=True, encoding="utf-8")


r = run("--features", "F-BILL-001", "--entities", "invoice")
out = r.stdout
check("it runs", r.returncode == 0, r.stderr)
all_ids = ["R-BILL-001", "R-BILL-002", "R-BILL-003", "R-BILL-004", "R-BILL-005", "R-USER-001"]
check("every card in every domain appears, in full or in the index", all(i in out for i in all_ids), out)
full_ids = set(re.findall(r'"id": "(R-[A-Z]+-\d+)"', out))
check("a card naming the module's feature is in full", "R-BILL-001" in full_ids, full_ids)
check("an invariant on an entity the module writes is in full, with no feature naming it", "R-BILL-003" in full_ids, full_ids)
check("an invariant on another entity is only indexed", "R-BILL-004" not in full_ids and "- R-BILL-004 [invariant]" in out)
check("a card on another feature is only indexed, and long text is cut",
      "R-BILL-002" not in full_ids and re.search(r"- R-BILL-002 \[validation\] A negative amount is rejected with 422 .*…", out) is not None)
check("the header says how many were filtered", "billing.yaml: 2 in full, 3 filtered to the index, 5 cards in all" in out, out[:900])
check("with no --entities no invariant is pulled in", "R-BILL-003" not in set(re.findall(r'"id": "(R-[A-Z]+-\d+)"', run("--features", "F-BILL-001").stdout)))
check("--domains limits the files read", "R-USER-001" not in run("--features", "F-BILL-001", "--domains", "billing").stdout)
check("no features is refused", run().returncode == 1)
o = run("--features", "F-USER-001", "--out", "plan/rules-for/S1-users.md")
check("--out writes the file", o.returncode == 0 and os.path.exists(os.path.join(wb, "plan/rules-for/S1-users.md")), o.stdout + o.stderr)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
