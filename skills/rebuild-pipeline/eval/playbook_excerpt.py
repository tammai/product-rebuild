#!/usr/bin/env python3
"""playbook_excerpt.py (eval) — does `playbook.py excerpt` give a drafter its sections and nothing else?

  python3 skills/rebuild-pipeline/eval/playbook_excerpt.py

WHY IT EXISTS. An ADR drafter that reads an excerpt instead of the whole playbook is only as good as the
excerpt: a missing section is a decision drafted without its default, silently. So for every concern of both
registered playbooks this asserts the excerpt carries each section the `concerns:` map names (and those of a
concern it is decided after), is a small fraction of the playbook, and carries no other numbered section.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
PB = os.path.join(HERE, "..", "references", "playbooks")
sys.path.insert(0, SCRIPTS)
import playbook  # noqa: E402

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


def cli(*a):
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "playbook.py"), *a], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


for name in ("web-modular-monolith", "mobile-flutter"):
    path = os.path.join(PB, name + ".md")
    raw = open(path, encoding="utf-8").read()
    meta = playbook.parse_playbook_meta(raw)
    bad, worst = [], 0.0
    for concern, val in meta["concerns"].items():
        code, out, err = cli("excerpt", concern, "--playbook", path)
        if code != 0:
            bad.append(f"{concern}: exit {code} {err}")
            continue
        chain, todo = [], [concern]
        while todo:  # the closure: what it is decided after, and what those are decided after
            c = todo.pop()
            if c not in chain:
                chain.append(c)
                todo += meta["decide_before"].get(c, [])
        named = sorted({t for c in chain for t in re.findall(r"§\s*([0-9]+(?:\.[0-9]+)*)", meta["concerns"][c])} | {"1"})
        heads = set(re.findall(r"^#{2,6}\s+([0-9]+(?:\.[0-9]+)*)[.):]?(?=\s)", out, re.M))
        top = lambda n: n.split(".")[0]  # noqa: E731
        missing = [n for n in named if n not in heads]
        extra = sorted(h for h in heads if top(h) not in {top(n) for n in named})
        if missing or extra:
            bad.append(f"{concern}: missing {missing}, extra {extra}")
        if all(meta["concerns"][c].strip().upper() == "N/A" for c in chain) and "no default" not in out:
            bad.append(f"{concern}: an N/A concern does not say so")
        worst = max(worst, len(out) / len(raw))
    check(f"{name}: every concern's excerpt carries its named sections and no others", not bad, "\n".join(bad))
    check(f"{name}: the largest excerpt is under 50% of the playbook ({worst:.0%})", worst < 0.5)

check("an unknown concern is refused", cli("excerpt", "nope", "--playbook", os.path.join(PB, "web-modular-monolith.md"))[0] == 1)
check("a decide-before concern includes its upstream's sections",
      "concerns.background-workers" in cli("excerpt", "events-queues", "--playbook", os.path.join(PB, "web-modular-monolith.md"))[1])
check("no arguments prints usage", cli()[0] == 1)
# read_adrs must read the header forms drafters actually write (see _adr_field in playbook.py).
import shutil  # noqa: E402
import tempfile  # noqa: E402

forms = {
    "bare": "status: proposed\nconcern: storage\norg-default: §8\ndecision: mirror-default\n",
    "bullet": "- status: proposed\n- concern: storage\n- org-default: §8\n- decision: mirror-default\n",
    "bold bullet": "- **status:** proposed\n- **concern:** storage\n- **org-default:** §8 Data\n- **decision:** mirror-default\n",
    "bold key": "**concern**: storage\n**org-default**: §8\n",
    "backticked": "concern: `storage`\norg-default: `adr/playbook.md` §8\n",
}
for label, body in forms.items():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "adr"))
    open(os.path.join(d, "adr", "ADR-001.md"), "w").write("# ADR\n\n" + body)
    got = playbook.read_adrs(d)
    check(f"read_adrs reads a {label} header", bool(got) and got[0]["concern"] == "storage" and bool(got[0]["org_default"]), got)
    shutil.rmtree(d)
d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, "adr"))
open(os.path.join(d, "adr", "ADR-001.md"), "w").write("# ADR\n\nThe concern: here is prose, and org-default: also.\n")
check("read_adrs does not take a field out of running prose", playbook.read_adrs(d)[0]["concern"] is None)
shutil.rmtree(d)

print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
