#!/usr/bin/env python3
"""gp.py — GP's execution record: each NFR's own stated verification, run against the production candidate, with
its evidence (spec 05 P8). Run from the workbench root.

  python3 scripts/gp.py nfr      # write or extend parity/gp/nfr-evidence.md from rspec's docs/nfr.md
  python3 scripts/gp.py check    # every NFR has evidence and a result; every drill names who performed it

WHY. rspec's nfr.md already says how each requirement is proven (its Verification column: "k6 load test in CI",
"restore drill, timed"). A readiness checklist ticked from memory is an assertion; P8 asks for the stated
verification RUN against the production candidate, with the evidence linked. This script runs nothing itself:
load tests run where the NFR says, and drills stay the user's to perform (GP: "the USER performs the drills").
It keeps the record and refuses an incomplete one, and gate.py's Gate 5 check calls the same check().

THE RECORD. One row per NFR: `| NFR | Requirement | Verification | Evidence | Result | Performed by |`. Result is
`pass`, `fail` or `n/a: <reason>`. A row is complete with evidence and `pass` or `n/a: <reason>`. A drill (its
Verification names a drill, restore, failover, rollback, incident or dry run) also needs who performed it.
Re-running `nfr` keeps every filled row and adds NFRs that are new in nfr.md.
"""
from __future__ import annotations

import os
import re
import sys

NFR = os.path.join("docs", "nfr.md")
EVIDENCE = os.path.join("parity", "gp", "nfr-evidence.md")
DRILL = re.compile(r"drill|restore|failover|fail-over|rollback|roll back|incident|dry[ -]run", re.I)
HEADER = "| NFR | Requirement | Verification | Evidence | Result | Performed by |"


def read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        return re.sub(r"\r\n?", "\n", fh.read())


def _cells(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def nfr_rows(path=NFR):
    """[(id, requirement, verification)] from rspec's nfr.md table, columns found by their header names."""
    if not os.path.exists(path):
        return []
    out, cols = [], None
    for line in read_text(path).splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = _cells(line)
        if cols is None and any(c.lower().startswith("verification") for c in cells):
            cols = {"req": next((i for i, c in enumerate(cells) if c.lower().startswith("requirement")), 2),
                    "ver": next(i for i, c in enumerate(cells) if c.lower().startswith("verification"))}
            continue
        if cols and cells and re.fullmatch(r"NFR-[A-Za-z0-9-]+", cells[0]):
            out.append((cells[0], cells[cols["req"]] if len(cells) > cols["req"] else "",
                        cells[cols["ver"]] if len(cells) > cols["ver"] else ""))
    return out


def evidence_rows(path=EVIDENCE):
    """{id: [nfr, requirement, verification, evidence, result, by]} from the record."""
    out = {}
    for line in read_text(path).splitlines() if os.path.exists(path) else []:
        cells = _cells(line)
        if len(cells) >= 6 and re.fullmatch(r"NFR-[A-Za-z0-9-]+", cells[0]):
            out[cells[0]] = cells[:6]
    return out


def problems(root="."):
    """What keeps the NFR record from being complete; [] when it is."""
    nfrs = nfr_rows(os.path.join(root, NFR))
    if not nfrs:
        return [f"{NFR} has no NFR rows (rspec:tech writes them; goal production needs a Verification for each)"]
    rows = evidence_rows(os.path.join(root, EVIDENCE))
    out = []
    for nid, _req, ver in nfrs:
        r = rows.get(nid)
        if not r:
            out.append(f"{nid}: not in {EVIDENCE} (run python3 scripts/gp.py nfr)")
            continue
        evidence, result, by = r[3], r[4].lower(), r[5]
        if not evidence:
            out.append(f"{nid}: no evidence for \"{ver}\"")
        elif result != "pass" and not re.match(r"n/a:\s*\S", result):
            out.append(f"{nid}: result is {r[4] or 'empty'} (pass, or n/a: <reason>)")
        elif DRILL.search(ver) and not by:
            out.append(f"{nid}: \"{ver}\" is a drill, and no one is named as having performed it")
    return out


def cmd_nfr():
    nfrs = nfr_rows()
    if not nfrs:
        print(f"gp: {NFR} has no NFR rows.", file=sys.stderr)
        return 1
    old = evidence_rows()
    lines = ["# NFR evidence (GP)", "",
             "Each NFR's own Verification, run against the production candidate. Evidence is a link or path; Result is "
             "`pass`, `fail` or `n/a: <reason>`; a drill names who performed it. Drills are the user's to perform.", "",
             HEADER, "|---|---|---|---|---|---|"]
    for nid, req, ver in nfrs:
        keep = old.get(nid)
        lines.append("| " + " | ".join([nid, req, ver] + (keep[3:6] if keep else ["", "", ""])) + " |")
    os.makedirs(os.path.dirname(EVIDENCE), exist_ok=True)
    with open(EVIDENCE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"{EVIDENCE}: {len(nfrs)} NFRs, {sum(1 for n, _, _ in nfrs if n in old)} carried over.")
    return 0


def cmd_check():
    p = problems()
    for x in p:
        print(f"  {x}")
    print("NFR evidence: complete." if not p else f"NFR evidence: {len(p)} incomplete.")
    return 1 if p else 0


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("gp: no locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    if args[:1] == ["nfr"]:
        return cmd_nfr()
    if args[:1] == ["check"]:
        return cmd_check()
    print("Usage: gp.py nfr | check", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
