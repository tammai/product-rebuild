#!/usr/bin/env python3
"""boundary.py — the mechanical half of a slice boundary, in one call. Run from the workbench root.

  python3 scripts/boundary.py S3            # archive the slice's lane plans, parity, slice review, re-mine status
  python3 scripts/boundary.py remine-done   # record that the upstream re-mine ran today

WHY IT EXISTS. The between-slices sequence (g5-build.md) was four to six orchestrator turns, each one
re-reading the whole session: archive each lane's plan, run parity.py, run slice_review.py, then work out
whether the upstream re-mine was due. None of those steps takes a decision. This runs them in the order
that works (archive first, so the slice review reads each plan in its final state; parity second) and prints
what each said, so the orchestrator makes one call and then reads one result. What stays with the
orchestrator is every decision: recording the slice's outcome in plan/progress.yaml (parity reads it, so do
that BEFORE this), acting on the review, and writing the runbook.

RE-MINE. g6-parity.md step 3 re-runs lane A against the reference's latest release. It sat in the
every-slice run with no date attached, so a project with nine slices re-mined nine times against a
reference that ships monthly, each one a miner run. The date of the last re-mine lives in
parity/last-remine (one ISO date, committed with the report). This prints DUE or not due against a
30-day interval, and "frozen, no re-mine" when sources.yaml says `reference.upstream: frozen`. It does not
run the re-mine: that is a miner dispatch, and `remine-done` records that one happened.

EXIT CODES. 0: every step ran and nothing needs a look. 2: something needs the orchestrator: a lane plan
that would not archive (unfinished rows, or already archived is fine and not counted), a step that failed,
or a re-mine that is due. The output says which.

It calls the workbench's own scripts through the same interpreter that runs it, so it is the same on every
machine. Zero-dependency, like the scripts it calls.
"""
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REMINE_FILE = os.path.join("parity", "last-remine")
REMINE_DAYS = 30


def _run(script, *args):
    return subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _remine_status():
    """(text, due) for the upstream re-mine."""
    src = open("sources.yaml", encoding="utf-8").read().replace("\r\n", "\n") if os.path.exists("sources.yaml") else ""
    block = re.search(r"^reference:\n((?:[ \t]+.*\n|\n)*)", src, re.M)
    if block and re.search(r"^[ \t]+upstream:[ \t]*[\"']?frozen[\"']?[ \t]*(?:#.*)?$", block.group(1), re.M):
        return "Upstream re-mine: reference is frozen, no re-mine.", False
    if not os.path.exists(REMINE_FILE):
        return "Upstream re-mine: DUE. None is recorded. After it runs: python3 scripts/boundary.py remine-done", True
    raw = open(REMINE_FILE, encoding="utf-8").read().strip()
    try:
        last = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return f"Upstream re-mine: DUE. {REMINE_FILE} holds {raw!r}, not a date. After it runs: python3 scripts/boundary.py remine-done", True
    age = (date.today() - last).days
    if age >= REMINE_DAYS:
        return f"Upstream re-mine: DUE. Last on {raw}, {age} days ago (interval {REMINE_DAYS}). After it runs: python3 scripts/boundary.py remine-done", True
    return f"Upstream re-mine: not due. Last on {raw}, {age} days ago (interval {REMINE_DAYS}).", False


def _remine_done():
    os.makedirs("parity", exist_ok=True)
    today = date.today().isoformat()
    with open(REMINE_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(today + "\n")
    print(f"Recorded the upstream re-mine as of {today} in {REMINE_FILE}. Commit it with the parity report.")
    return 0


def _boundary(slice_id):
    attention = False
    rec_path = os.path.join("plan", "lane-plans", f"{slice_id}.yaml")
    lanes = []
    if os.path.exists(rec_path):
        body = re.sub(r"^#.*\n", "", open(rec_path, encoding="utf-8").read(), flags=re.M)
        try:
            lanes = sorted(((json.loads(body) or {}).get("lanes") or {}).keys())
        except ValueError:
            print(f"== lane plans: {rec_path} is not readable JSON; archive each lane with lane_plan.py by hand.")
            attention = True
    print(f"== {slice_id}: archive lane plans ({len(lanes)} recorded)")
    for lane in lanes:
        r = _run("lane_plan.py", "archive", slice_id, lane)
        text = (r.stdout + r.stderr).strip()
        if r.returncode != 0 and "already archived" in text:
            print(f"  {lane}: already archived")
        elif r.returncode != 0:
            attention = True
            print(f"  {lane}: NOT archived. {text}")
        else:
            print(f"  {lane}: {text}")
    for label, script, args in (("parity", "parity.py", []), ("slice review", "slice_review.py", [slice_id])):
        r = _run(script, *args)
        out = (r.stdout + r.stderr).strip()
        print(f"\n== {label}")
        print(out if out else "(no output)")
        if r.returncode != 0:
            attention = True
            print(f"  {script} exited {r.returncode}.")
    text, due = _remine_status()
    print(f"\n== {text}")
    return 2 if (attention or due) else 0


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = sys.argv[1:] if argv is None else list(argv)
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    if args and args[0] == "remine-done":
        return _remine_done()
    if args and re.fullmatch(r"S\d+", args[0]):
        return _boundary(args[0])
    print("Usage: boundary.py <Sn> | remine-done", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
