#!/usr/bin/env python3
"""gp_eval.py (eval) — 3.0.0, spec 05 P8–P10: does Gate 5 refuse on each condition P8 names, does GP hold every
NFR to its own stated verification, do the budgets reach the scripts that spend them, does each slice's cost
show beside its quality figures, and does a parked decision block only what depends on it?

  python3 skills/rebuild-pipeline/eval/gp_eval.py [gate5|nfr|budgets|cost|park]

WHY IT EXISTS. Gate 5 is terminal: nothing after it catches a hidden test that never ran, a departure nobody
decided or a restore drill nobody did. Each refusal is checked one at a time against a workbench that otherwise
passes, so a check that stopped firing shows up as a lock that should have been refused. No model call. With an
argument it runs one group, which is how the change file's acceptance tests name them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SCRIPTS = os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts")
CONTRACTS = os.path.join(ROOT, "contracts", "v1", "contracts.py")
ONLY = sys.argv[1] if len(sys.argv) > 1 else None

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'' if ok or not detail else chr(10) + '      ' + str(detail)}")
    if not ok:
        failures += 1


base = tempfile.mkdtemp(prefix="gp-eval-")
ENV = {"GIT_AUTHOR_NAME": "Eval", "GIT_AUTHOR_EMAIL": "eval@x", "GIT_COMMITTER_NAME": "Eval",
       "GIT_COMMITTER_EMAIL": "eval@x", "RSPEC_PLUGIN_ROOT": os.path.join(base, "no-rspec")}


def run(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, **ENV, **(env or {})})


def w(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def commit(d):
    run(["git", "add", "-A"], d)
    run(["git", "commit", "-qm", "eval"], d)


NFR = ("| ID | Quality characteristic (ISO/IEC 25010) | Requirement (measurable) | Features | Verification | Why | Tag |\n"
       "|---|---|---|---|---|---|---|\n"
       "| NFR-01 | Performance | p95 below 300 ms at peak | F-ISS-01 | k6 load test in CI | slow pages lose users | [docs] |\n"
       "| NFR-02 | Reliability | restore within 1 hour | — | restore drill, timed | data is the product | [docs] |\n")


def project(name):
    proj = os.path.join(base, name)
    os.makedirs(proj)
    r = run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "p", "--dir", proj], proj)
    check(f"{name}: rebuild_init creates the workbench", r.returncode == 0, r.stderr)
    wb = os.path.join(proj, "p-workbench")
    w(wb, "docs/rspec.json", json.dumps({"product": "p", "goal": "production", "stage": "handoff",
                                         "reference": {"run": {"kind": "local"}}}))
    w(wb, "docs/build-plan.md", "# Build plan\n\n## Slice 1: issues\n\n| 1 | F-ISS-01 a |\n")
    rows = [{"id": f"F-ISS-01.AC{i}", "feature": "F-ISS-01", "file": "features/F-ISS-01.md", "text_sha256": "0" * 64,
             "tag": "observed", "priority": "MVP", "level": 2, "test": None, "departures": []} for i in (1, 2)]
    w(wb, "docs/criteria.lock.json", json.dumps({"contracts": "1.1.1", "spec": "docs", "generated": "2026-11-08T00:00:00Z",
                                                 "criteria": rows}, indent=2))
    w(wb, "docs/acceptance/manifest.json", json.dumps({"contracts": "1.1.1", "tests": []}))
    w(wb, "docs/departures.yaml", "[]\n")
    w(wb, "docs/nfr.md", NFR)
    w(wb, "docs/production-readiness.md", "# Production readiness\n\n## Security\n- [x] Secrets scanned in CI (ci.yml)\n")
    w(wb, "plan/holdout.json", json.dumps({"seed": 1, "count": 1, "list_sha256": "0" * 64, "hidden": ["F-ISS-01.AC2"],
                                           "slices": {"S1": ["F-ISS-01.AC2"]}}))
    w(wb, "parity/holdout/S1.json", json.dumps({"slice": "S1", "results": [
        {"criterion": "F-ISS-01.AC2", "runner": "http", "result": "pass", "observed": ""}]}))
    for rel in ("docs/features.md", "docs/domain.md"):
        w(wb, rel, "# x\n")
    commit(wb)
    return proj, wb


def script(wb, name, *a, env=None):
    return run([sys.executable, os.path.join("scripts", name), *a], wb, env)


def fill_evidence(wb, drill_by="Tam Mai"):
    script(wb, "gp.py", "nfr")
    p = os.path.join(wb, "parity", "gp", "nfr-evidence.md")
    text = read(p)
    text = re.sub(r"(?m)^\| NFR-01 \|(.*?)\|(.*?)\|.*$", r"| NFR-01 |\1|\2| ci run 812 (k6 report) | pass | CI |", text)
    text = re.sub(r"(?m)^\| NFR-02 \|(.*?)\|(.*?)\|.*$", rf"| NFR-02 |\1|\2| docs/drills/restore.md | pass | {drill_by} |", text)
    w(wb, "parity/gp/nfr-evidence.md", text)


def gate5(wb):
    probe = "import sys; sys.path.insert(0, 'scripts'); import gate; sys.exit(gate._lock_gate5_checks('gate-5') or 0)"
    return run([sys.executable, "-c", probe], wb)


if ONLY in (None, "gate5"):
    print("\n# Gate 5 refuses on each of P8's conditions (AC-010)")
    proj, wb = project("gate5")
    fill_evidence(wb)
    r = gate5(wb)
    check("a workbench that meets every condition passes Gate 5's checks", r.returncode == 0, r.stdout + r.stderr)

    def refused(label, rel, text, needle):
        before = read(wb, rel) if os.path.exists(os.path.join(wb, rel)) else None
        w(wb, rel, text)
        r = gate5(wb)
        check(f"refuses: {label}", r.returncode == 1 and needle in r.stderr, r.stdout + r.stderr)
        if before is None:
            os.remove(os.path.join(wb, rel))
        else:
            w(wb, rel, before)

    refused("an unchecked readiness item", "docs/production-readiness.md",
            "# Production readiness\n\n## Reliability\n- [ ] Automated backups, and a restore drill done and timed\n",
            "restore drill done and timed")
    refused("an NFR without evidence", "parity/gp/nfr-evidence.md",
            re.sub(r"(?m)^\| NFR-01 .*$", "| NFR-01 | p95 below 300 ms at peak | k6 load test in CI |  |  |  |",
                   read(wb, "parity", "gp", "nfr-evidence.md")), "NFR-01")
    refused("a hidden test that did not run", "parity/holdout/S1.json", json.dumps({"slice": "S1", "results": [
        {"criterion": "F-ISS-01.AC2", "runner": "http", "result": "not run", "observed": "ACCEPT_BASE_URL is not set"}]}),
            "F-ISS-01.AC2")
    finding = {"id": "BH-0001", "source": "bug-hunter", "class": "build-defect", "severity": "high",
               "criterion": "F-ISS-01.AC1", "rule": None,
               "repro": {"runner": "http", "steps": [{"request": {"method": "GET", "path": "/x"}, "expect": {"status": 200}}]},
               "observed": {"rebuild": "500", "reference": "200"}, "route": "sdlc",
               "verified_by": {"agent": "repro-verifier", "result": "reproduced"}}
    refused("an open high finding", "parity/findings/S1/BH-0001.json", json.dumps(finding), "BH-0001")
    refused("a proposed departure", "docs/departures.yaml",
            '- id: D-001\n  kind: simplification\n  summary: keys differ\n  status: proposed\n', "D-001")
    lock = json.loads(read(wb, "docs", "criteria.lock.json"))
    lock["criteria"][0]["level"] = 0
    refused("an MVP criterion below level 1", "docs/criteria.lock.json", json.dumps(lock), "F-ISS-01.AC1")

    print("\n# goal production is forced (AC-010)")
    rspec = json.loads(read(wb, "docs", "rspec.json"))
    w(wb, "docs/rspec.json", json.dumps(dict(rspec, goal="learn", stage="features-approved")))
    commit(wb)
    r = script(wb, "gate.py", "lock", "gate-1", "--by", "Eval")
    check("gate-1 refuses a rebuild whose rspec goal is not production", r.returncode == 1 and "production" in r.stderr,
          r.stdout + r.stderr)

if ONLY in (None, "nfr"):
    print("\n# GP holds each NFR to its stated verification (AC-023)")
    proj, wb = project("nfr")
    r = script(wb, "gp.py", "nfr")
    ev = read(wb, "parity", "gp", "nfr-evidence.md") if r.returncode == 0 else ""
    check("gp.py nfr lists every NFR with its own Verification", "| NFR-01 | p95 below 300 ms at peak | k6 load test in CI |" in ev
          and "| NFR-02 | restore within 1 hour | restore drill, timed |" in ev, r.stdout + r.stderr + ev)
    r = script(wb, "gp.py", "check")
    check("with no evidence, check fails naming each NFR", r.returncode == 1 and "NFR-01" in r.stdout + r.stderr
          and "NFR-02" in r.stdout + r.stderr, r.stdout + r.stderr)
    fill_evidence(wb, drill_by="")
    r = script(wb, "gp.py", "check")
    check("a drill with evidence but no one who performed it still fails", r.returncode == 1 and "NFR-02" in r.stdout + r.stderr
          and "NFR-01" not in r.stdout + r.stderr, r.stdout + r.stderr)
    fill_evidence(wb)
    w(wb, "docs/nfr.md", NFR + "| NFR-03 | Security | TLS everywhere | — | header scan in CI | x | [docs] |\n")
    script(wb, "gp.py", "nfr")
    ev = read(wb, "parity", "gp", "nfr-evidence.md")
    check("re-running keeps the filled rows and adds the new NFR",
          "ci run 812 (k6 report)" in ev and "| Tam Mai |" in ev and "| NFR-03 |" in ev, ev)

if ONLY in (None, "budgets"):
    print("\n# budgets reach the scripts that spend them (AC-024)")
    proj, wb = project("budgets")
    y = read(wb, "rebuild.yaml")
    check("rebuild.yaml is scaffolded with P9's budgets",
          all(re.search(rf"^  {k}: {v}\b", y, re.M) for k, v in (("parallel_lanes", 3), ("recorders", 4),
              ("hunters_per_slice", 6), ("bughunter_tokens_per_slice", 1200000), ("fix_rounds", 2))), y)
    r = script(wb, "boundary.py", "S1")
    check("boundary's bug-hunter command carries the slice's hunters, budget and cost log",
          "--max 6" in r.stdout and "--budget 1200000" in r.stdout and "--cost-log logs/S1/cost.jsonl" in r.stdout, r.stdout[-900:])
    w(wb, "rebuild.yaml", y.replace("fix_rounds: 2", "fix_rounds: 1"))
    f = {"id": "BH-0001", "source": "bug-hunter", "class": "environment", "severity": "low", "criterion": None, "rule": None,
         "repro": {"runner": "http", "steps": [{"request": {"method": "GET", "path": "/x"}, "expect": {"status": 200}}]},
         "observed": {"rebuild": "x", "reference": "y"}, "route": "orchestrator",
         "verified_by": {"agent": "repro-verifier", "result": "reproduced"}}
    w(wb, "parity/findings/S1/BH-0001.json", json.dumps(f))
    script(wb, "route.py", "S1")
    r = script(wb, "route.py", "S1")
    check("route.py's round cap is budgets.fix_rounds", r.returncode == 1 and "1 fix round" in r.stderr, r.stdout + r.stderr)

if ONLY in (None, "cost"):
    print("\n# each slice's cost beside its quality figures (AC-025)")
    proj, wb = project("cost")
    r = script(wb, "boundary.py", "S1")
    check("with no cost log, the boundary says cost was not run", "cost: not run: no cost log" in r.stdout, r.stdout[-600:])
    for stage, tin in (("build", 1000), ("build", 500), ("g6", 300)):
        r = script(wb, "cost.py", "add", "--slice", "S1", "--stage", stage, "--plugin", "product-rebuild", "--agent", "lane-worker",
                   "--tier", "sonnet", "--wall-s", "60", "--turns", "10", "--tokens-in", str(tin), "--tokens-out", "100",
                   "--result", "ok")
    logp = os.path.join(wb, "logs", "S1", "cost.jsonl")
    ok = os.path.exists(logp) and run([sys.executable, CONTRACTS, "cost", logp], base).returncode == 0
    check("cost.py add appends contracts C7 lines to logs/<Sn>/cost.jsonl", ok and len(read(logp).splitlines()) == 3, r.stderr)
    r = script(wb, "boundary.py", "S1")
    check("boundary prints the slice's cost by stage", re.search(r"build: 2 runs.*1500 in", r.stdout) is not None
          and re.search(r"g6: 1 run.*300 in", r.stdout) is not None, r.stdout[-900:])

if ONLY in (None, "park"):
    print("\n# a parked decision blocks only what depends on it (AC-026)")
    proj, wb = project("park")
    r = script(wb, "autopilot.py", "park", "--what", "human-sample", "--slice", "S1", "--note", "user away")
    check("autopilot.py park records the decision", r.returncode == 0, r.stdout + r.stderr)
    b1 = script(wb, "autopilot.py", "blocked", "boundary:S1")
    b2 = script(wb, "autopilot.py", "blocked", "lanes:S2")
    b5 = script(wb, "autopilot.py", "blocked", "gate-5")
    check("the parked sample blocks S1's boundary and Gate 5, naming it", b1.returncode == 1 and "human-sample" in b1.stdout
          and b5.returncode == 1, b1.stdout + b5.stdout)
    check("…and not the next slice's lanes", b2.returncode == 0, b2.stdout + b2.stderr)
    script(wb, "autopilot.py", "park", "--what", "feature-drop", "--note", "F-ISS-09 is used")
    check("a parked feature drop blocks Gate 1", script(wb, "autopilot.py", "blocked", "gate-1").returncode == 1)
    r = script(wb, "autopilot.py", "unpark", "--what", "human-sample", "--slice", "S1")
    check("unpark lifts it", r.returncode == 0 and script(wb, "autopilot.py", "blocked", "boundary:S1").returncode == 0,
          r.stdout + r.stderr)

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
