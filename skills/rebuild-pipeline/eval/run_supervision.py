#!/usr/bin/env python3
"""run_supervision.py (eval) — 0.31.0, issue #1: the G5 gaps found in a real run.

  python3 skills/rebuild-pipeline/eval/run_supervision.py

Scaffolds a throwaway workbench with rebuild_init.py and a code repo registered in repos.yaml,
then runs the REAL scripts against it:
  - run_phases.py: phases in order, `NAME=value` reaching later phases, a stop at the first
    failure, and the status files lanes_check reads;
  - lanes_check.py: a dead driver is a stall with the newest file named, a live one is not, a
    JUnit skip is not counted as a pass, and a code repo with no marker is named mid-slice;
  - parity.py: a skip-heavy run and an env-var skip are both NOT GREEN;
  - pause_check.py: a missing or wrong marker mid-slice is an issue.
Each case asserts on what a script printed or wrote, as dates_and_reruns.py does.

The phases are run by the same interpreter as this eval (`sys.executable`), not a bare `python3`
or `node`: a phase that shelled out to whatever was first on PATH would make the eval pass or fail
by machine.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

SCRIPTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "scripts")
base = tempfile.mkdtemp(prefix="rebuild-eval-")


def _cmd(script, args):
    return [sys.executable, os.path.join("scripts", script), *args]


subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "evalwb", "--dir", base],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
wb = os.path.join(base, "evalwb-workbench")


def w(rel, text):
    path = os.path.join(wb, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def run(script, *args):
    r = subprocess.run(_cmd(script, args), cwd=wb, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return {"out": r.stdout + r.stderr, "code": r.returncode}


def read(rel):
    p = os.path.join(wb, rel)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def exists(rel):
    return os.path.exists(os.path.join(wb, rel))


# Local calendar date, from local fields: the scripts name their files this way, and a UTC date
# here would disagree with them for part of every day (see dates_and_reruns.py).
date = time.strftime("%Y-%m-%d")

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + detail.replace("\n", "\n      "))


def py_phase(code):
    """A phases.txt command that runs `code` with this interpreter. `code` uses single quotes only,
    so one double-quoted argument works in both sh and cmd.exe."""
    exe = f'"{sys.executable}"' if os.name == "nt" else shlex.quote(sys.executable)
    return f'{exe} -c "{code}"'


# A code repo, committed, registered in repos.yaml, with S2 in progress.
app = os.path.join(base, "app")
os.mkdir(app)


def g(*a):
    subprocess.run(["git", "-C", app, *a], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


g("init", "-q")
with open(os.path.join(app, "a.txt"), "w", encoding="utf-8", newline="\n") as f:
    f.write("a\n")
g("add", ".")
g("-c", "user.email=e@x", "-c", "user.name=e", "commit", "-qm", "init")
w("repos.yaml", "repos:\n  - name: app\n    path: ../app\n")
w("plan/progress.yaml", "slices:\n  S1: done\n  S2: in-progress\n")

# --- 1. run_phases: order, env carry-over, stop at the first failure -------------------------
RUN = f"parity/runs/{date}-joint"
w(f"{RUN}/phases.txt", "\n".join([
    "# the joint run",
    "EVAL_DB_URL=postgres://eval",
    "one: " + py_phase(f"import os; open('{RUN}/seen.txt', 'w').write(os.environ.get('EVAL_DB_URL') or 'UNSET')"),
    "two: " + py_phase("import sys; sys.exit(3)"),
    "three: " + py_phase("print('should not run')"),
]) + "\n")
r1 = run("run_phases.py", RUN)
check("run-phases exits with the failing phase's code", r1["code"] == 3, r1["out"])
check("a NAME=value line reaches a later phase", read(f"{RUN}/seen.txt") == "postgres://eval", read(f"{RUN}/seen.txt"))
check("each phase that ran has a .done file",
      bool(re.search(r"exit=0", read(f"{RUN}/one.done"))) and bool(re.search(r"exit=3", read(f"{RUN}/two.done"))))
check("no phase runs after a failure",
      not exists(f"{RUN}/three.log") and bool(re.search(r"Not run, because two failed: three", r1["out"])), r1["out"])
st1 = json.loads(read(f"{RUN}/status.json") or "{}")
check("status.json records the failed phase",
      st1.get("state") == "failed" and st1.get("phase") == "two" and st1.get("exit") == 3, json.dumps(st1))
check("the run directory is gitignored", read("parity/runs/.gitignore").strip() == "*")


def _malformed_refused():
    w("parity/runs/bad/phases.txt", "one: true\nthis is not a phase\n")
    r = run("run_phases.py", "parity/runs/bad")
    return r["code"] == 1 and bool(re.search(r"line 2", r["out"])) and not exists("parity/runs/bad/status.json")


check("a malformed phases.txt is refused before anything runs", _malformed_refused())
shutil.rmtree(os.path.join(wb, "parity/runs/bad"))

# --- 2. lanes_check: a driver that died mid-phase is a stall, and the newest file is named ----
w(f"{RUN}/status.json", json.dumps({"pid": 999999, "state": "running", "phase": "go", "phases": ["go"], "results": []}))
w(f"{RUN}/go.log", "--- PASS: TestX\n")
r2 = run("lanes_check.py")
check("a dead driver exits 2", r2["code"] == 2, r2["out"])
check("a dead driver is named with its phase",
      bool(re.search(r"driver for parity/runs/[\d-]+-joint died during phase go", r2["out"])), r2["out"])
check("the stall names the newest file and its age",
      bool(re.search(r"Newest file anywhere: .*(go\.log|status\.json), written \d+ min ago", r2["out"])), r2["out"])

# --- 3. a live driver is a run in progress, even with no test process -------------------------
sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
w(f"{RUN}/status.json", json.dumps({"pid": sleeper.pid, "state": "running", "phase": "redeploy", "phases": ["redeploy"], "results": []}))
r3 = run("lanes_check.py", "--idle", "0")
sleeper.kill()
sleeper.wait()
check("a live driver is not a stall", r3["code"] == 0 and bool(re.search(r"running phase redeploy", r3["out"])), r3["out"])
shutil.rmtree(os.path.join(wb, "parity/runs"))

# --- 4. lanes_check and the markers ---------------------------------------------------------
r4 = run("lanes_check.py")
check("lanes-check names a repo with no marker mid-slice",
      bool(re.search(r"MARKER: S2 in progress", r4["out"])) and bool(re.search(r"app: no \.rebuild-workbench marker", r4["out"])), r4["out"])
p4 = run("pause_check.py")
check("pause-check names a repo with no marker mid-slice",
      bool(re.search(r"app: no `\.rebuild-workbench` marker while S2 is in progress", p4["out"])), p4["out"])


def write_marker(text):
    with open(os.path.join(app, ".rebuild-workbench"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")


write_marker(os.path.join(base, "elsewhere"))
check("pause-check names a marker pointing elsewhere",
      bool(re.search(r"app: `\.rebuild-workbench` points at .*elsewhere, not this workbench", run("pause_check.py")["out"])))
write_marker(wb)
check("a correct marker is not named",
      not re.search(r"rebuild-workbench", run("pause_check.py")["out"]) and not re.search(r"MARKER", run("lanes_check.py")["out"]))
os.remove(os.path.join(app, ".rebuild-workbench"))
w("plan/progress.yaml", "slices:\n  S1: done\n")
check("no slice in progress: no marker issue", not re.search(r"rebuild-workbench", run("pause_check.py")["out"]))

# --- 5. skips: not counted as passes, and NOT GREEN beyond the bounds -----------------------
def junit(cases):
    def one(c):
        name, st = c[0], c[1]
        why = c[2] if len(c) > 2 else None
        if st == "passed":
            return f'<testcase classname="F-A-001" name="{name}"/>'
        if st == "skipped":
            return f'<testcase classname="F-A-001" name="{name}"><skipped message="{why}"/></testcase>'
        return f'<testcase classname="F-A-001" name="{name}"><failure message="x">x</failure></testcase>'
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<testsuites><testsuite name="ac">\n'
            + "\n".join(one(c) for c in cases) + "\n</testsuite></testsuites>\n")


w("matrix/features.yaml", "- id: F-A-001\n  name: Alpha\n  status: planned\n")
w("plan/slices.yaml", "- id: S1\n  name: One\n  features: [F-A-001]\n")
many = [[f"t{i}", "skipped" if i < 4 else "passed", "only runs on iOS"] for i in range(10)]
w(f"parity/{date}-ac.xml", junit(many))
check("lanes-check does not count a skip as a pass", bool(re.search(r"6/10 passed, 4 skipped", run("lanes_check.py")["out"])))
run("parity.py")
rep5 = read(f"parity/{date}.md")
check("a 40% skip run is NOT GREEN", bool(re.search(r"NOT GREEN: 4 of 10 tests skipped \(40%\)", rep5)), rep5[:900])
check("skips are grouped by reason", bool(re.search(r"4 × only runs on iOS", rep5)))

w(f"parity/{date}-ac.xml", junit([[f"t{i}", "passed"] for i in range(19)] + [["t19", "skipped", "TEST_DATABASE_URL not set"]]))
run("parity.py")
rep6 = read(f"parity/{date}.md")
check("one env-var skip is NOT GREEN under the ratio bound",
      bool(re.search(r"NOT GREEN: 1 skipped because an environment variable was unset", rep6))
      and not re.search(r"tests skipped \(5%\)", rep6), rep6[:900])

w(f"parity/{date}-ac.xml", junit([[f"t{i}", "passed"] for i in range(19)] + [["t19", "skipped", "only runs on iOS"]]))
run("parity.py")
check("one platform skip in twenty is not flagged", not re.search(r"NOT GREEN", read(f"parity/{date}.md")), read(f"parity/{date}.md")[:900])

shutil.rmtree(base, ignore_errors=True)
print(f"\n{f'{failures} FAILED' if failures else 'all passed'}")
sys.exit(1 if failures else 0)
