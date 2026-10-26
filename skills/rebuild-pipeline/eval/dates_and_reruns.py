#!/usr/bin/env python3
"""dates_and_reruns.py (eval) — E11 (local-calendar dates) and E12 (rerun evidence), 0.19.0.

  python3 skills/rebuild-pipeline/eval/dates_and_reruns.py

Scaffolds a throwaway workbench with rebuild_init.py, then writes JUnit files and run records and
runs the REAL parity.py and slice_review.py against them. Every case asserts on the reports those
scripts write, never on a function in isolation: the failures these guard against were all in how a
report picked and labelled a file.

THE DATE SPLIT IS FORCED, NOT HOPED FOR. The scripts run under a TZ whose local date differs
from the UTC date at the moment the eval runs (UTC+14 when the UTC hour is 10 or later, UTC-12
before that), so a script still naming files by the UTC date fails every time, not only on
local mornings east of UTC.

How TZ reaches the scripts differs by platform. On POSIX the Olson names `Etc/GMT-14` and
`Etc/GMT+12` go in the child's environment, and this process computes its own expected dates by
switching its own TZ with time.tzset(), so the expected dates come from the same machinery the
scripts use. Windows has no tzset and its C runtime reads TZ only in the `UTC-14` form (POSIX
sign convention: a minus sign is EAST of UTC), not Olson names, so there the child gets that form
and the expected dates are computed from the fixed offset. The Windows path has not been run.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

SCRIPTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "scripts")

UTC_NOW = datetime.now(timezone.utc)
TZ_HOURS = 14 if UTC_NOW.hour >= 10 else -12
if os.name == "nt":
    TZ = "UTC-14" if TZ_HOURS == 14 else "UTC+12"
else:
    TZ = "Etc/GMT-14" if TZ_HOURS == 14 else "Etc/GMT+12"
# What the banner prints, and what the JavaScript eval called it, on every platform.
TZ_LABEL = "Etc/GMT-14" if TZ_HOURS == 14 else "Etc/GMT+12"


def day_in(days=0):
    """Local date in TZ, offset by `days`. Computed here the way the scripts must: from local fields."""
    instant = time.time() + days * 86400
    if hasattr(time, "tzset"):
        old = os.environ.get("TZ")
        os.environ["TZ"] = TZ
        time.tzset()
        try:
            return time.strftime("%Y-%m-%d", time.localtime(instant))
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
    return datetime.fromtimestamp(instant, timezone(timedelta(hours=TZ_HOURS))).strftime("%Y-%m-%d")


today, yesterday, tomorrow = day_in(0), day_in(-1), day_in(1)
utc_today = UTC_NOW.strftime("%Y-%m-%d")
if today == utc_today:
    print(f"eval setup: TZ {TZ_LABEL} did not split the date from UTC ({today}).", file=sys.stderr)
    sys.exit(1)

base = tempfile.mkdtemp(prefix="rebuild-eval-")
subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "evalwb", "--dir", base],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
wb = os.path.join(base, "evalwb-workbench")


def _cmd(script, args):
    return [sys.executable, os.path.join("scripts", script), *args]


def w(rel, text):
    path = os.path.join(wb, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


w("matrix/features.yaml", "- id: F-A-001\n  name: Alpha\n  status: planned\n")
w("plan/slices.yaml", "- id: S1\n  name: One\n  features: [F-A-001]\n")
w("plan/progress.yaml", "slices: { S1: deployed }\nfeatures: { F-A-001: covered }\n")


def junit(cases):
    def one(c):
        name, st = c
        if st == "passed":
            return f'<testcase classname="F-A-001" name="{name}"/>'
        return f'<testcase classname="F-A-001" name="{name}"><failure message="x">x</failure></testcase>'
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<testsuites><testsuite name="ac">\n'
            + "\n".join(one(c) for c in cases) + "\n</testsuite></testsuites>\n")


def _iso_now():
    # JavaScript's toISOString(): UTC, milliseconds, `Z`.
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def meta(shas, dirty=False):
    return json.dumps({
        "started": _iso_now(),
        "repos": {n: {"path": f"/x/{n}", "sha": sha, "dirty": dirty} for n, sha in shas.items()},
    }, separators=(",", ":"))


def reset_parity():
    shutil.rmtree(os.path.join(wb, "parity"), ignore_errors=True)
    os.mkdir(os.path.join(wb, "parity"))


def run(script, *args):
    r = subprocess.run(_cmd(script, args), cwd=wb, env={**os.environ, "TZ": TZ}, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout + r.stderr


def report(rel):
    p = os.path.join(wb, rel)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + detail.replace("\n", "\n      "))


def has(pattern, text):
    return re.search(pattern, text) is not None


# --- 1. the date split: today's LOCAL file is the one read, and named, by both reports -------
reset_parity()
w(f"parity/{yesterday}-ac.xml", junit([["t1", "passed"], ["t2", "passed"]]))
w(f"parity/{today}-ac.xml", junit([["t1", "passed"], ["t2", "passed"], ["t3", "passed"]]))
run("parity.py")
check("parity names its report by the local date", os.path.exists(os.path.join(wb, f"parity/{today}.md")),
      f"no parity/{today}.md (UTC date is {utc_today})")
check("parity reads today's local JUnit", has(r"AC pass rate: 3/3", report(f"parity/{today}.md")), report(f"parity/{today}.md")[:400])
run("slice_review.py", "S1")
sr1 = report("plan/slice-reviews/S1.md")
check("slice-review reads today's local run and calls it today", has(r"3/3 passed", sr1) and has(r"\(today\)", sr1), sr1[:600])
check("slice-review raises no date warning for a same-day run", not has(r"WARNING: no joint run for today", sr1))

# --- 2. a file dated AHEAD of today is a warning, never "(today)" ---------------------------
reset_parity()
w(f"parity/{tomorrow}-ac.xml", junit([["t1", "passed"]]))
run("slice_review.py", "S1")
sr2 = report("plan/slice-reviews/S1.md")
check("an ahead-dated run leads with a warning", has(r"WARNING: no joint run for today", sr2) and has(r"AHEAD of today", sr2), sr2[:600])
check("an ahead-dated run is not labelled (today)", not has(r"\(today\)", sr2))

# --- 3. an old run is announced, not presented as current -----------------------------------
reset_parity()
w(f"parity/{yesterday}-ac.xml", junit([["t1", "passed"]]))
run("slice_review.py", "S1")
check("a day-old run leads with a warning", has(r"WARNING: no joint run for today[^\n]*1 day\(s\) old", report("plan/slice-reviews/S1.md")))

# --- 4. failed then passed on the SAME commits: PASS, labelled flaky, same rate everywhere --
reset_parity()
w(f"parity/{today}-ac.xml", junit([["t1", "passed"], ["t2", "failed"], ["t3", "failed"]]))
w(f"parity/{today}-ac-rerun.xml", junit([["t2", "passed"], ["t3", "failed"]]))
w(f"parity/{today}-ac.meta.json", meta({"workbench": "aaa111", "backend": "bbb222"}))
w(f"parity/{today}-ac-rerun.meta.json", meta({"workbench": "aaa111", "backend": "bbb222"}))
run("parity.py")
run("slice_review.py", "S1")
p4, sr4 = report(f"parity/{today}.md"), report("plan/slice-reviews/S1.md")
check("flaky: parity counts the rerun pass", has(r"AC pass rate: 2/3 passed \(67%\), 1 of them flaky", p4), p4[:700])
check("flaky: slice-review states the same rate", has(r"2/3 passed \(67%\), 1 of them flaky", sr4), sr4[:700])
check("flaky: the rerun pass is labelled flaky", has(r"Passed on rerun — flaky", sr4))
check("flaky: the joint run's own total stays visible", has(r"Joint run: 1/3 passed", sr4))
check("flaky: the still-failing test is named", has(r"Still failing after the rerun: F-A-001 › t3", sr4))

# --- 5. failed then passed on DIFFERENT commits: labelled code-changed, with the range -------
w(f"parity/{today}-ac-rerun.meta.json", meta({"workbench": "aaa111", "backend": "ccc333"}))
run("slice_review.py", "S1")
sr5 = report("plan/slice-reviews/S1.md")
check("code-changed: labelled, not flaky", has(r"Passed on rerun — code-changed", sr5) and not has(r"of them flaky", sr5), sr5[:700])
check("code-changed: names the repo and range", has(r"backend: `bbb222\.\.ccc333`", sr5))

# --- 6. a run record missing: unverified, never a silent PASS -------------------------------
os.remove(os.path.join(wb, f"parity/{today}-ac-rerun.meta.json"))
run("slice_review.py", "S1")
check("missing record: labelled unverified", has(r"Passed on rerun — unverified", report("plan/slice-reviews/S1.md")))

# --- 7. a rerun file is never mistaken for a joint run --------------------------------------
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import acsuite  # noqa: E402  (after the workbench exists, as the JavaScript imported it dynamically)

files = acsuite.ac_junit_files(wb)
check("acJunitFiles ignores -ac-rerun.xml",
      all(not f["path"].endswith("-ac-rerun.xml") for f in files) and len(files) == 1)

# --- 8. a failing test that did not exist last run is "new", not "already failing" ----------
reset_parity()
w(f"parity/{yesterday}-ac.xml", junit([["t1", "passed"]]))
w(f"parity/{today}-ac.xml", junit([["t1", "passed"], ["t9", "failed"]]))
run("slice_review.py", "S1")
sr8 = report("plan/slice-reviews/S1.md")
check("a new failing test is labelled new",
      has(rf"Failing, new since `{yesterday}`[^\n]*\n\s+- F-A-001 › t9", sr8), sr8[:900])
check("a new failing test is not labelled already failing", not has(r"already failing on", sr8))

shutil.rmtree(base, ignore_errors=True)
print(f"\n{f'{failures} FAILED' if failures else 'all passed'} (TZ {TZ_LABEL}: local {today}, UTC {utc_today})")
sys.exit(1 if failures else 0)
