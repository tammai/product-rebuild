#!/usr/bin/env python3
"""check.py — the objective half of the drafter A/B: is the ADR well-formed, correctly labelled and cited?

  python3 check.py <concern> <run-dir>      # prints JSON

structure_ok: the required fields exist, `concern:` equals the key, status is `proposed`.
decision_ok: `decision:` is one of the values truth.json allows for this concern. Two concerns have a
reference fact that makes the playbook default wrong (a divergence is the right call), and two have none (a
divergence there is an invented one). sections_ok: `org-default:` cites every section the concerns map names.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
truth = json.load(open(os.path.join(HERE, "..", "truth.json")))
concern, d = sys.argv[1], sys.argv[2]
files = glob.glob(os.path.join(d, "adr", "ADR-*.md"))
res = {"written": bool(files)}
if files:
    t = open(files[0]).read()
    field = lambda k: (re.search(rf"^{k}:\s*(.+)$", t, re.M) or [None, ""])[1].strip().strip("`\"'")  # noqa: E731
    res["decision"] = field("decision")
    res["structure_ok"] = (field("concern") == concern and field("status") == "proposed"
                           and all(re.search(rf"^{k}:", t, re.M) for k in ("concern", "org-default", "decision", "status")))
    res["decision_ok"] = res["decision"] in truth[concern]["allowed_decisions"]
    od = field("org-default")
    res["sections_ok"] = all(s in od for s in truth[concern]["sections"])
    res["chars"] = len(t)
print(json.dumps(res))
