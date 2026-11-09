#!/usr/bin/env python3
"""g6_eval.py (eval) — 3.0.0, spec 05 P6 and P7: does a slice boundary run G6 cheapest first and stop at the
first fix it needs, does every finding go where contracts C6 says, does the human sample become findings,
and does one departures registry explain differences everywhere?

  python3 skills/rebuild-pipeline/eval/g6_eval.py [route|boundary|sample|departures|fix|remine|reference|equiv]

WHY IT EXISTS. G6 is where a build is judged against the reference rather than against its own tests. A
boundary that runs the expensive steps over a build with a known defect wastes the budget; a router that
sends a spec gap to a build lane gets the spec "fixed" in code; a difference accepted in one log and not
another passes one check and fails the next. This builds a workbench with rebuild_init.py, a spec, lock and
bundle written by hand, a local HTTP server standing in for the slice build, and a stub sdlc state.py (the
boundary eval/lane_plan.py tests for real). No model call. With an argument it runs one group, which is how
the change file's acceptance tests name them.
"""
from __future__ import annotations

import glob
import hashlib
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading

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


base = tempfile.mkdtemp(prefix="g6-eval-")
# The holdout and its local config go to a per-user data folder; an eval must never write the real one.
os.environ["PRODUCT_REBUILD_DATA"] = os.path.join(base, "user-data")
STUB = os.path.join(base, "sdlc-stub")
ENV = {"GIT_AUTHOR_NAME": "Eval", "GIT_AUTHOR_EMAIL": "eval@x", "GIT_COMMITTER_NAME": "Eval",
       "GIT_COMMITTER_EMAIL": "eval@x", "SDLC_PLUGIN_ROOT": STUB, "RSPEC_PLUGIN_ROOT": os.path.join(base, "no-rspec")}


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


w(STUB, "scripts/state.py", r'''import json, os, sys
a = sys.argv[1:]
root = a[a.index("--root") + 1] if "--root" in a else "."
with open(os.path.join(root, ".sdlc", "stub-calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(a) + "\n")
cmd = [x for x in a if x != "--root" and x != root]
if cmd[0] == "new":
    p = os.path.join(root, ".sdlc", "state", cmd[1] + ".md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write("# %s\nStatus: active\nCurrent: Stage 1 – Define\n\n## Stages\n- [ ] 1 Define\n"
                                         "- [ ] 2 Build\n- [ ] 3 Review\n- [ ] 4 Ship\n" % cmd[1])
    print(json.dumps({"ok": True, "event": {"state": ".sdlc/state/%s.md" % cmd[1]}}))
else:
    print(json.dumps({"ok": True}))
''')

# The slice build: answers /api/<criterion> with {"key": "OK"} unless MODE says otherwise. "flaky" fails
# the first request for a criterion and passes after.
MODE, SEEN = {}, {}


class Build(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        cid = self.path.rsplit("/", 1)[-1]
        mode = MODE.get(cid, "ok")
        SEEN[cid] = SEEN.get(cid, 0) + 1
        good = mode == "ok" or (mode == "flaky" and SEEN[cid] > 1)
        body = json.dumps({"key": "OK" if good else "WRONG"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


server = socketserver.TCPServer(("127.0.0.1", 0), Build)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{server.server_address[1]}"

# Slice 1: F-ISS-01 (3 criteria at level 2), F-ISS-02 (level 1, rspec's reason), F-ISS-03 (1 at level 2). D4 hides
# exactly one, from F-ISS-01, so F-ISS-03.AC1 is always open.
CRITERIA = [("F-ISS-01", 1, 2), ("F-ISS-01", 2, 2), ("F-ISS-01", 3, 2), ("F-ISS-02", 1, 1), ("F-ISS-03", 1, 2)]


def project(name, split=True):
    proj = os.path.join(base, name)
    os.makedirs(proj)
    run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "p", "--dir", proj], proj)
    wb = os.path.join(proj, "p-workbench")
    app = os.path.join(proj, "app")
    os.makedirs(app)
    run(["git", "init", "-q", "-b", "main"], app)
    w(app, ".sdlc/config.json", '{"docs_dir": "docs/sdlc"}\n')
    w(app, ".gitmodules", '[submodule "workbench"]\n\tpath = workbench\n\turl = ../p-workbench\n')
    commit(app)
    w(wb, "repos.yaml", "repos:\n  - name: app\n    path: ../app\n")
    w(wb, "docs/rspec.json", json.dumps({"product": "p", "goal": "production", "stage": "handoff", "reference": {"run": {"kind": "local"}}}))
    w(wb, "docs/build-plan.md", "# Build plan\n\n## Slice 1: issues\n\n| 1 | F-ISS-01 a |\n| 2 | F-ISS-02 b |\n| 3 | F-ISS-03 c |\n")
    rows, tests = [], []
    for feat, n, level in CRITERIA:
        cid = f"{feat}.AC{n}"
        path = f"http/{cid}.yaml" if level == 2 else None
        rows.append({"id": cid, "feature": feat, "file": f"features/{feat}.md", "text_sha256": "0" * 64, "tag": "observed",
                     "priority": "MVP", "level": level, "test": f"acceptance/{path}" if path else None, "departures": []})
        if path:
            body = (f"criterion: {cid}\nsteps:\n  - request: {{method: GET, path: /api/{cid}}}\n"
                    f"    expect:\n      status: 200\n      json:\n        - {{pointer: /key, equals: \"OK\"}}\n")
            w(wb, f"docs/acceptance/{path}", body)
            tests.append({"criterion": cid, "runner": "http", "path": path, "sha256": hashlib.sha256(body.encode()).hexdigest(),
                          "level": "integration", "visibility": "open", "normalize": []})
    w(wb, "docs/criteria.lock.json", json.dumps({"contracts": "1.1.1", "spec": "docs", "generated": "2026-11-08T00:00:00Z",
                                                 "criteria": rows}, indent=2))
    w(wb, "docs/acceptance/manifest.json", json.dumps({"contracts": "1.1.1", "tests": tests}, indent=2))
    w(wb, "docs/verify/outcomes.jsonl", json.dumps({"criterion": "F-ISS-02.AC1", "outcome": "unrecordable"}) + "\n")
    w(wb, "docs/departures.yaml", "[]\n")
    for rel in ("docs/features.md", "docs/domain.md"):
        w(wb, rel, "# x\n")
    commit(wb)
    if split:
        r = run([sys.executable, os.path.join("scripts", "holdout.py"), "split", "--seed", "5"], wb)
        check(f"{name}: holdout split", r.returncode == 0, r.stdout + r.stderr)
        commit(wb)
    return proj, wb


def script(wb, name, *a, env=None):
    return run([sys.executable, os.path.join("scripts", name), *a], wb, env)


def finding(fid, cls, criterion=None, verified="reproduced", source="bug-hunter"):
    route = {"build-defect": "sdlc", "test-defect": "sdlc", "spec-gap": "rspec", "reference-defect": "human",
             "accepted-departure": "drop", "flaky": "orchestrator", "environment": "orchestrator"}[cls]
    return {"id": fid, "source": source, "class": cls, "severity": "high", "criterion": criterion, "rule": None,
            "repro": {"runner": "http", "steps": [{"request": {"method": "GET", "path": "/api/x"}, "expect": {"status": 200}}]},
            "observed": {"rebuild": f"{fid} rebuild said WRONG", "reference": "OK"}, "route": route,
            "verified_by": {"agent": "repro-verifier", "result": verified}}


def valid(path):
    return run([sys.executable, CONTRACTS, "finding", path], base).returncode == 0


if ONLY in (None, "route", "fix"):
    print("\n# route.py (AC-009)")
    proj, wb = project("route", split=False)
    w(wb, "docs/departures.yaml", '- id: D-001\n  kind: deliberate-change\n  criteria: [F-ISS-01.AC2]\n  summary: keys differ\n'
                                  '  match:\n    - {runner: http, rule: "regex:WRONG"}\n'
                                  '  decided_by: "Tam Mai, 2026-11-08"\n'
                                  '- id: D-002\n  kind: deliberate-change\n  criteria: [F-ISS-01.AC1]\n  summary: human-only\n'
                                  '  match: []\n  decided_by: "Tam Mai, 2026-11-08"\n')
    fs = [finding("BH-0001", "build-defect", "F-ISS-01.AC1"), finding("BH-0002", "spec-gap", "F-ISS-03.AC1"),
          finding("BH-0003", "reference-defect"), finding("BH-0004", "environment"),
          finding("BH-0005", "build-defect", "F-ISS-03.AC1", verified="not-reproduced"),
          finding("BH-0006", "accepted-departure"), finding("BH-0007", "build-defect", "F-ISS-01.AC2"),
          finding("BH-0008", "build-defect")]
    for f in fs:
        w(wb, f"parity/findings/S1/{f['id']}.json", json.dumps(f, indent=2))
    commit(wb)
    r = script(wb, "route.py", "S1")
    plan = read(wb, "plan", "fix-rounds", "S1-r1.md") if r.returncode == 0 else ""

    def section(name):
        m = re.search(rf"^## {name}\b[\s\S]*?(?=^## |\Z)", plan, re.M)
        return m.group(0) if m else ""
    check("route.py writes round 1", r.returncode == 0, r.stdout + r.stderr)
    check("build-defect -> one sdlc fix lane per feature, with the lane_plan command",
          "BH-0001" in section("sdlc") and "lane_plan.py S1 fix-r1-f-iss-01" in section("sdlc") and "--fix 1" in section("sdlc"),
          section("sdlc"))
    check("spec-gap -> rspec:amend", "BH-0002" in section("rspec"), section("rspec"))
    check("reference-defect -> human (copy it or add a departure)", "BH-0003" in section("human"), section("human"))
    check("environment -> orchestrator", "BH-0004" in section("orchestrator"), section("orchestrator"))
    check("not reproduced -> not routed", "BH-0005" in section("not routed") and "BH-0005" not in section("sdlc"), plan)
    check("accepted-departure and a finding a decided departure explains are dropped",
          "BH-0006" in section("dropped") and "BH-0007" in section("dropped") and "D-001" in section("dropped"), section("dropped"))
    # The smoke run re-ran route.py with no fix in between and got a round 2 identical to round 1, burning the cap.
    r2 = script(wb, "route.py", "S1")
    check("a re-run with the same findings and no fix commit opens no round, and says round 1 is still open",
          r2.returncode == 0 and not os.path.exists(os.path.join(wb, "plan", "fix-rounds", "S1-r2.md"))
          and "round 1" in r2.stdout and "still open" in r2.stdout, r2.stdout + r2.stderr)
    # Only a recorded attempt opens the next round: commits and branches say nothing about which round they fix.
    app = os.path.join(proj, "app")
    w(app, "unrelated.txt", "work on something else\n")
    commit(app)
    r2 = script(wb, "route.py", "S1")
    check("…and a commit in a code repo is not an attempt", not os.path.exists(os.path.join(wb, "plan", "fix-rounds", "S1-r2.md"))
          and "still open" in r2.stdout and "--attempted" in r2.stdout, r2.stdout + r2.stderr)
    r2 = script(wb, "route.py", "S1", "--attempted", "restarted the flaky harness")
    r2b = script(wb, "route.py", "S1")
    check("…after route.py --attempted, a fix that did not work opens round 2 with the same findings",
          r2.returncode == 0 and r2b.returncode == 0 and os.path.exists(os.path.join(wb, "plan", "fix-rounds", "S1-r2.md"))
          and "restarted the flaky harness" in read(wb, "plan", "fix-rounds", "S1.json"), r2.stdout + r2.stderr + r2b.stdout + r2b.stderr)
    # The other way an attempt is recorded: lane_plan.py archive of one of the round's fix lanes.
    p2, wb2 = project("route-archive", split=False)
    w(wb2, "parity/findings/S1/BH-0004.json", json.dumps(finding("BH-0004", "environment"), indent=2))
    commit(wb2)
    script(wb2, "route.py", "S1")
    w(wb2, "plan/lane-plans/S1.yaml", "# eval\n" + json.dumps({"lanes": {"fix-r1-x": {"fix_round": 1,
                                                                                       "archived": {"at": "2026-11-09"}}}}))
    r2 = script(wb2, "route.py", "S1")
    check("an archived fix lane of round 1 is an attempt: the same findings open round 2",
          os.path.exists(os.path.join(wb2, "plan", "fix-rounds", "S1-r2.md")), r2.stdout + r2.stderr)
    script(wb, "route.py", "S1", "--attempted", "another try")
    r3 = script(wb, "route.py", "S1")
    check("a third round is refused: the user decides", r3.returncode == 1 and "user" in r3.stderr and
          not os.path.exists(os.path.join(wb, "plan", "fix-rounds", "S1-r3.md")), r3.stdout + r3.stderr)

    if ONLY in (None, "fix"):
        print("\n# a fix lane from findings (AC-022)")
        app = os.path.join(proj, "app")
        run(["git", "worktree", "add", "-q", "-b", "slice/S1-fix-r1-f-iss-01", os.path.join(proj, "app-fix")], app)
        r = script(wb, "lane_plan.py", "S1", "fix-r1-f-iss-01", "--worktree", "../app-fix", "--fix", "1",
                   "--findings", "BH-0001,BH-0008", "--approved-by", "Eval")
        changes = glob.glob(os.path.join(proj, "app-fix", "docs", "sdlc", "changes", "*.md"))
        change = read(changes[0]) if changes else ""
        check("the fix lane cites the finding's criterion", r.returncode == 0 and "- **AC-001** → F-ISS-01.AC1" in change,
              r.stdout + r.stderr + change)
        check("…and restates a finding with no criterion from what the build did",
              re.search(r"^- \*\*AC-002\*\* — `BH-0008`: .*BH-0008 rebuild said WRONG", change, re.M) is not None, change)
        calls = [json.loads(l) for l in read(proj, "app-fix", ".sdlc", "stub-calls.jsonl").splitlines()]
        new = next((c for c in calls if "new" in c), [])
        check("sdlc gets only the cited criteria", new[new.index("--criteria") + 1:] == ["F-ISS-01.AC1"] if "--criteria" in new
              else False, new)
        run(["git", "worktree", "add", "-q", "-b", "slice/S1-fix-r1-x", os.path.join(proj, "app-x")], app)
        r = script(wb, "lane_plan.py", "S1", "fix-r1-x", "--worktree", "../app-x", "--fix", "1", "--findings", "BH-0002",
                   "--approved-by", "Eval")
        check("a finding round 1 did not route to sdlc is refused", r.returncode == 1 and "BH-0002" in r.stderr, r.stdout + r.stderr)

if ONLY in (None, "boundary"):
    print("\n# the G6 sequence (AC-019)")
    proj, wb = project("boundary")
    hidden = json.loads(read(wb, "plan", "holdout.json"))["hidden"]
    MODE.update({"F-ISS-01.AC1": "bad", "F-ISS-01.AC2": "bad", "F-ISS-01.AC3": "bad", "F-ISS-03.AC1": "flaky"})
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL})
    out = r.stdout + r.stderr
    found = sorted(glob.glob(os.path.join(wb, "parity", "findings", "S1", "*.json")))
    crits = sorted(json.loads(read(p))["criterion"] for p in found)
    open_bad = sorted(c for c in ("F-ISS-01.AC1", "F-ISS-01.AC2", "F-ISS-01.AC3") if c not in hidden)
    check("a failing open test, still failing on its one re-run, becomes a reproduced build-defect finding",
          r.returncode == 2 and crits == open_bad and all(valid(p) for p in found), out + str(crits))
    check("a test that passes on its re-run is flaky, not a finding", "F-ISS-03.AC1" not in crits and "re-run" in out, out)
    check("the boundary stops there: hidden suite not run, route.py named",
          not os.path.exists(os.path.join(wb, "parity", "holdout", "S1.json")) and "route.py S1" in out, out)
    MODE.update({c: "ok" for c in ("F-ISS-01.AC1", "F-ISS-01.AC2", "F-ISS-01.AC3")})
    script(wb, "route.py", "S1", "--close", ",".join(json.loads(read(p))["id"] for p in found))
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL})
    out = r.stdout + r.stderr
    check("with the findings closed it goes on: hidden suite run and green",
          json.loads(read(wb, "parity", "holdout", "S1.json"))["results"][0]["result"] == "pass", out)
    check("…prints the bug-hunter command, and does not pass without it and the human sample",
          r.returncode == 2 and "bug-hunter:hunt --oracle" in out and "--format finding-v1 --out parity/findings/S1/" in out
          and "--yes" in out, out)
    script(wb, "boundary.py", "hunted", "S1")
    script(wb, "boundary.py", "sample", "S1", "--seed", "2")
    review = read(wb, "plan", "slice-reviews", "S1.md")
    review = re.sub(r"(?m)^(- F-[A-Z0-9-]+:)[ \t]*$", r"\1 agree", review).replace("Reviewer: <your name>", "Reviewer: Tam Mai")
    w(wb, "plan/slice-reviews/S1.md", review)
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL})
    check("open and hidden green, bug-hunter run, sample recorded: the boundary passes",
          r.returncode == 0 and "PASS" in r.stdout, r.stdout + r.stderr)
    closed_before = [json.loads(read(p))["id"] for p in found]

    def boundary():
        r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL})
        return r.returncode, r.stdout + r.stderr

    mpath = os.path.join(wb, "docs", "acceptance", "manifest.json")
    m = json.loads(read(mpath))
    m["tests"].append({"criterion": "F-ISS-03.AC1", "runner": "playwright", "path": "e2e/F-ISS-03.AC1.spec.ts",
                       "sha256": "0" * 64, "level": "e2e", "visibility": "open", "normalize": []})
    w(wb, "docs/acceptance/manifest.json", json.dumps(m, indent=2))
    w(wb, "docs/acceptance/e2e/F-ISS-03.AC1.spec.ts", "// e2e\n")
    rc, out = boundary()
    check("an open Playwright test with no joint-run JUnit is not run, and the boundary does not pass",
          rc == 2 and "F-ISS-03.AC1: not run: no joint-run JUnit" in out, out)
    import time
    w(proj, f"app/parity/{time.strftime('%Y-%m-%d')}-ac.xml",
      '<testsuite><testcase classname="e2e" name="F-ISS-03.AC1 shows the total"/></testsuite>\n')
    rc, out = boundary()
    check("a JUnit left in a code repo is not read: the joint run's file is the workbench's", rc == 2, out)
    w(wb, f"parity/{time.strftime('%Y-%m-%d')}-ac.xml",
      '<testsuite><testcase classname="e2e" name="F-ISS-03.AC1 shows the total"/></testsuite>\n')
    rc, out = boundary()
    check("…read from the joint run's JUnit in the workbench's parity/, a passing case for it lets the boundary pass", rc == 0 and "PASS" in out, out)
    good = read(wb, "plan", "slice-reviews", "S1.md")
    first = re.findall(r"(?m)^- (F-[A-Z0-9-]+): agree$", good)[0]
    w(wb, "plan/slice-reviews/S1.md", good.replace(f"- {first}: agree", f"- {first}: differs: total is off (class: build-defect, severity: high)"))
    rc, out = boundary()
    hs = glob.glob(os.path.join(wb, "parity", "findings", "S1", "HS-*.json"))
    check("a recorded 'differs' line is a finding at the boundary without route.py having run, and holds it",
          rc == 2 and len(hs) == 1 and "PASS" not in out, out)
    script(wb, "route.py", "S1", "--close", "HS-0001")
    w(wb, "plan/slice-reviews/S1.md", good.replace(f"- {first}: agree", f"- {first}: differs: total is off"))
    rc, out = boundary()
    check("a 'differs' line with no class is not a recorded sample", rc == 2 and "not recorded for" in out, out)
    w(wb, "plan/slice-reviews/S1.md", good)
    regress = open_bad[0]
    MODE[regress] = "bad"
    rc, out = boundary()
    new_ids = [json.loads(read(p))["id"] for p in glob.glob(os.path.join(wb, "parity", "findings", "S1", "BND-*.json"))
               if json.loads(read(p))["id"] not in closed_before]
    check("a criterion failing again after its finding was closed gets a new finding, routed again",
          rc == 2 and len(new_ids) == 1 and f"new finding {new_ids[0]}" in out, out)
    MODE[regress] = "ok"
    script(wb, "route.py", "S1", "--close", ",".join(new_ids))
    os.replace(os.path.join(wb, ".rebuild-plugin"), os.path.join(wb, ".rebuild-plugin.off"))
    rc, out = boundary()
    os.replace(os.path.join(wb, ".rebuild-plugin.off"), os.path.join(wb, ".rebuild-plugin"))
    check("without contracts.py the open findings are not counted as none: the boundary does not pass",
          rc == 2 and "PASS" not in out and "not run" in out and "contracts" in out, out)

if ONLY in (None, "sample"):
    print("\n# the human sample (AC-020)")
    proj, wb = project("sample", split=False)
    r = script(wb, "boundary.py", "sample", "S1", "--seed", "4")
    review = read(wb, "plan", "slice-reviews", "S1.md") if r.returncode == 0 else ""
    picked = re.findall(r"(?m)^- (F-[A-Z0-9-]+):[ \t]*$", review)
    check("sample picks the slice's features (all 3 here: P6 takes 2 or 3) with the seed recorded",
          sorted(picked) == ["F-ISS-01", "F-ISS-02", "F-ISS-03"] and "Seed: 4" in review, r.stdout + r.stderr + review)
    again = os.path.join(base, "sample-again")
    shutil.copytree(proj, again)
    os.remove(os.path.join(again, "p-workbench", "plan", "slice-reviews", "S1.md"))
    script(os.path.join(again, "p-workbench"), "boundary.py", "sample", "S1", "--seed", "4")
    check("the same seed picks the same features in the same order",
          re.findall(r"(?m)^- (F-[A-Z0-9-]+):", read(again, "p-workbench", "plan", "slice-reviews", "S1.md")) == picked)
    review = review.replace("Reviewer: <your name>", "Reviewer: Tam Mai")
    review = re.sub(r"(?m)^- F-ISS-03:[ \t]*$", "- F-ISS-03: differs: total is off by one (class: build-defect)", review)
    review = re.sub(r"(?m)^(- F-ISS-0[12]:)[ \t]*$", r"\1 agree", review)
    w(wb, "plan/slice-reviews/S1.md", review)
    r = script(wb, "route.py", "S1")
    hs = glob.glob(os.path.join(wb, "parity", "findings", "S1", "HS-*.json"))
    f = json.loads(read(hs[0])) if hs else {}
    check("a 'differs' line becomes a reproduced finding, the reviewer as verifier, and is routed",
          len(hs) == 1 and valid(hs[0]) and f.get("verified_by") == {"agent": "Tam Mai", "result": "reproduced"}
          and f.get("class") == "build-defect" and "HS-0001" in read(wb, "plan", "fix-rounds", "S1-r1.md"), r.stdout + r.stderr + str(f))

if ONLY in (None, "departures"):
    print("\n# one departures registry (AC-021)")
    proj, wb = project("departures")
    hidden = json.loads(read(wb, "plan", "holdout.json"))["hidden"][0]
    MODE[hidden] = "bad"
    for label, match, want in (("a criterion-only departure (match: []) does not explain a live criterion's failure", "[]", "fail"),
                               ("a departure whose match rule does not cover the observed value explains nothing",
                                '[{runner: http, pointer: /key, rule: "regex:^OTHER$"}]', "fail"),
                               ("a hidden failure a decided departure's match rule covers is 'explained', not a failure",
                                '[{runner: http, pointer: /key, rule: "regex:^WRONG"}]', "explained")):
        w(wb, "docs/departures.yaml", f'- id: D-001\n  kind: simplification\n  criteria: [{hidden}]\n  summary: keys differ\n'
                                      f'  match: {match}\n  decided_by: "Tam Mai, 2026-11-08"\n')
        r = script(wb, "holdout.py", "run", "S1", env={"ACCEPT_BASE_URL": URL})
        res = json.loads(read(wb, "parity", "holdout", "S1.json"))["results"][0]
        check(label, res["result"] == want and (want == "fail" or "D-001" in res["observed"]), r.stdout + r.stderr)
    probe = ("import sys, json; sys.path.insert(0, 'scripts'); import departures; "
             "p = 'docs/criteria.lock.json'; d = json.load(open(p)); "
             "[c.update(priority='Drop') for c in d['criteria'] if c['id'] == sys.argv[1]]; "
             "json.dump(d, open(p, 'w')); print(departures.explains(sys.argv[1], 'http', '/key', 'WRONG'))")
    w(wb, "docs/departures.yaml", f'- id: D-001\n  kind: simplification\n  criteria: [{hidden}]\n  summary: dropped\n'
                                  f'  match: []\n  decided_by: "Tam Mai, 2026-11-08"\n')
    r = run([sys.executable, "-c", probe, hidden], wb)
    check("match: [] explains a criterion it names once that criterion is Drop", r.stdout.strip() == "D-001", r.stdout + r.stderr)
    run(["git", "checkout", "--", "docs/criteria.lock.json"], wb)
    w(wb, "docs/departures.yaml", f'- id: D-001\n  kind: simplification\n  criteria: [{hidden}]\n  summary: keys differ\n'
                                  f'  match:\n    - {{runner: http, pointer: /key, rule: "regex:^WRONG"}}\n  decided_by: "Tam Mai, 2026-11-08"\n')
    commit(wb)
    MODE[hidden] = "ok"
    r = script(wb, "flows.py", "unlock", "--acceptance", "--weakens", "--criteria", "F-ISS-03.AC1", "--by", "Tam Mai",
               "--reason", "status 201 is accepted as 200")
    dep = read(wb, "docs", "departures.yaml")
    check("flows.py unlock --weakens appends a decided departure for the criteria",
          r.returncode == 0 and "D-002" in dep and "F-ISS-03.AC1" in dep and "Tam Mai" in dep and "deliberate-change" in dep, r.stderr + dep)
    script(wb, "flows.py", "relock", "--acceptance")
    r = script(wb, "equiv.py", "accept", "invoices-total", "--by", "Tam Mai", "--reason", "rounding is deliberate")
    dep = read(wb, "docs", "departures.yaml")
    check("equiv.py accept writes a departure matching the trace, not a DECISIONS.md line",
          r.returncode == 0 and "equiv-trace:invoices-total" in dep and not os.path.exists(os.path.join(wb, "parity", "equiv", "DECISIONS.md")),
          r.stdout + r.stderr + dep)
    w(wb, "parity/2026-11-09-equiv.xml", '<testsuite><testcase classname="F-ISS-01" name="invoices-total"><failure message="x">d'
                                         '</failure></testcase><testcase classname="F-ISS-01" name="other"><failure message="x">d'
                                         '</failure></testcase></testsuite>\n')
    probe = "import sys; sys.path.insert(0, 'scripts'); import gate; sys.exit(gate._lock_gate5_checks('gate-5') or 0)"
    r = run([sys.executable, "-c", probe], wb)
    check("gate-5 refuses on a red trace no departure explains, naming only that one",
          r.returncode == 1 and "other" in r.stderr and "invoices-total" not in r.stderr.split("explains")[-1], r.stderr)
    decided_only = read(wb, "docs", "departures.yaml")
    w(wb, "docs/departures.yaml", "{bad: map}\n")
    v = script(wb, "validate.py")
    check("an unreadable registry fails validation, before gate-1 records anything",
          v.returncode == 1 and "could not be read" in v.stdout + v.stderr, v.stdout[-900:] + v.stderr)
    # Gate 1 records only what can stay as it is: deciding a proposed or undecided entry later would read as an
    # edit, and an ID that is not C5's D-<nnn> cannot be written into the lock and read back safely.
    for label, entry, named in (("a departure is proposed", "- id: D-009\n  kind: simplification\n  summary: idea\n"
                                                             "  status: proposed\n", "D-009"),
                                ("a departure has no decided_by", "- id: D-010\n  kind: simplification\n  summary: x\n",
                                 "D-010"),
                                ("a departure's decided_by is blank", '- id: D-012\n  kind: simplification\n  summary: x\n'
                                                                      '  decided_by: "  "\n', "D-012"),
                                ("a departure's ID is not D-<nnn>", '- id: "D 011: x"\n  kind: simplification\n  summary: x\n'
                                                                    '  decided_by: "Tam Mai"\n', "D 011")):
        w(wb, "docs/departures.yaml", decided_only + entry)
        commit(wb)
        rr = script(wb, "gate.py", "lock", "gate-1", "--by", "Eval")
        check(f"gate-1 refuses to lock while {label}, naming it",
              rr.returncode == 1 and named in rr.stderr, rr.stdout + rr.stderr)
    w(wb, "docs/departures.yaml", decided_only)
    commit(wb)
    rr = script(wb, "gate.py", "lock", "gate-1", "--by", "Eval")
    lock1 = read(wb, "locks", "gate-1.yaml")
    check("gate-1 records each departure present at its lock with a hash, and does not hash the registry",
          rr.returncode == 0 and all(re.search(rf"(?m)^  {d}: [0-9a-f]{{64}}$", lock1) for d in ("D-001", "D-002", "D-003"))
          and "docs/departures.yaml:" not in lock1, rr.stdout + rr.stderr + lock1)
    before = read(wb, "docs", "departures.yaml")
    r = script(wb, "flows.py", "unlock", "--acceptance", "--weakens", "--criteria", "F-ISS-03.AC1", "--by", "Tam Mai",
               "--reason", "another")
    dep = read(wb, "docs", "departures.yaml")
    v = script(wb, "validate.py")
    check("after gate-1, a decided departure is appended after the recorded ones and validates",
          r.returncode == 0 and dep.startswith(before.rstrip("\n")) and "- id: D-004" in dep[len(before.rstrip()):]
          and "recorded at the gate-1 lock" not in v.stdout + v.stderr, r.stdout + r.stderr + dep + v.stdout[-900:])
    probe_x = (f"import sys; sys.path.insert(0, 'scripts'); import departures; "
               f"print(departures.explained_by('{hidden}', 'http', '/key', 'WRONG'))")
    intact = run([sys.executable, "-c", probe_x], wb).stdout.strip()
    w(wb, "docs/departures.yaml", dep.replace("summary: keys differ", "summary: keys differ in any way", 1))
    v = script(wb, "validate.py")
    check("editing a departure gate-1 recorded fails validation, naming it as changed",
          v.returncode == 1 and "D-001 recorded at the gate-1 lock was changed" in v.stdout + v.stderr, v.stdout[-900:] + v.stderr)
    x = run([sys.executable, "-c", probe_x], wb)
    check("while a recorded departure is changed, no departure explains a difference (every reader fails closed)",
          intact == "D-001" and x.stdout.strip() == "None", intact + " / " + x.stdout + x.stderr)
    w(wb, "docs/departures.yaml", dep + "- id: D-099\n  1: x\n  kind: simplification\n  summary: x\n  decided_by: x\n")
    v = script(wb, "validate.py")
    check("an entry that cannot be hashed fails validation without a traceback",
          v.returncode == 1 and "Traceback" not in v.stdout + v.stderr and "could not be read" in v.stdout + v.stderr,
          v.stdout[-900:] + v.stderr)
    w(wb, "docs/departures.yaml", re.sub(r"(?ms)^- id: D-002\n.*?(?=^- id: |\Z)", "", dep))
    v = script(wb, "validate.py")
    check("removing a departure gate-1 recorded fails validation, naming it as removed",
          v.returncode == 1 and "D-002 recorded at the gate-1 lock was removed" in v.stdout + v.stderr, v.stdout[-900:] + v.stderr)
    probe5 = "import sys; sys.path.insert(0, 'scripts'); import gate; print(gate._gate5_problems())"
    g5 = run([sys.executable, "-c", probe5], wb)
    r = script(wb, "flows.py", "unlock", "--acceptance", "--weakens", "--criteria", "F-ISS-03.AC1", "--by", "Tam Mai",
               "--reason", "on a broken record")
    check("with a recorded departure removed, gate-5 lists it and adding another is refused",
          "D-002" in g5.stdout and r.returncode == 1 and "D-002" in r.stderr, g5.stdout + g5.stderr + r.stdout + r.stderr)
    w(wb, "docs/departures.yaml", dep)
    lock_now = read(wb, "locks", "gate-1.yaml")
    w(wb, "locks/gate-1.yaml", lock_now.replace("artifact_hashes:\n", "artifact_hashes:\n  docs/departures.yaml: " + "0" * 64 + "\n", 1))
    r = script(wb, "flows.py", "unlock", "--acceptance", "--weakens", "--criteria", "F-ISS-03.AC1", "--by", "Tam Mai",
               "--reason", "under an rc.1 lock")
    check("under a gate-1 lock that still hashes the registry (rc.1), adding a departure is refused, naming the reopen",
          r.returncode == 1 and "reopen" in r.stderr and read(wb, "docs", "departures.yaml") == dep, r.stdout + r.stderr)
    w(wb, "locks/gate-1.yaml", lock_now)

if ONLY in (None, "remine"):
    print("\n# the upstream re-mine: due every 30 days, done through rspec (docs/MIGRATION-3.md)")
    proj, wb = project("remine", split=False)
    w(wb, "sources.yaml", "reference:\n  kind: third-party\n  upstream: active\n")
    r = script(wb, "boundary.py", "S1")
    check("a re-mine never recorded is due, naming rspec's coverage pass and triage",
          "Upstream re-mine: DUE. None is recorded" in r.stdout and "rspec:features' coverage pass" in r.stdout
          and "rspec:features triage" in r.stdout, r.stdout[-900:] + r.stderr)
    check("remine-done records today's date", script(wb, "boundary.py", "remine-done").returncode == 0
          and re.fullmatch(r"\d{4}-\d\d-\d\d\n", read(wb, "parity", "last-remine")) is not None)
    check("a recorded re-mine is not due", "Upstream re-mine: not due. Last on" in script(wb, "boundary.py", "S1").stdout)
    w(wb, "parity/last-remine", "2020-01-01\n")
    check("a 30-day-old re-mine is due again",
          re.search(r"DUE\. Last on 2020-01-01, \d+ days ago", script(wb, "boundary.py", "S1").stdout) is not None)
    w(wb, "sources.yaml", "reference:\n  kind: own-code\n  upstream: frozen   # replaced app\n")
    check("a frozen reference says so", "reference is frozen, no re-mine" in script(wb, "boundary.py", "S1").stdout)

if ONLY in (None, "reference"):
    # The smoke run's G6 inherited ACCEPT_BASE_URL from rspec verify, which points at the reference: with the
    # reference up, the open suite would have tested the reference and passed.
    print("\n# G6 refuses to test the reference (S-54)")
    proj, wb = project("reference")
    src = read(wb, "sources.yaml")
    w(wb, "sources.yaml", re.sub(r"^(    base_url:).*$", lambda m: f'{m.group(1)} "{URL.replace("127.0.0.1", "localhost")}/"',
                                 src, count=1, flags=re.M))
    sent = sum(SEEN.values())
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL})
    out = r.stdout + r.stderr
    check("with ACCEPT_BASE_URL at the reference's address the boundary refuses, says why, and sends nothing",
          r.returncode == 2 and "REFUSED" in out and "reference.run.base_url" in out and "slice build" in out
          and sum(SEEN.values()) == sent, out[-1200:])
    r = script(wb, "holdout.py", "run", "S1", env={"ACCEPT_BASE_URL": URL})
    check("…and so does holdout.py run", r.returncode == 1 and "reference.run.base_url" in r.stderr
          and sum(SEEN.values()) == sent, r.stdout + r.stderr)
    # The same server under a path prefix, with sources.yaml written in another legal YAML layout, is still it.
    w(wb, "sources.yaml", f'reference:   # the app we replace\n# a comment at column 0\n  kind: own-code\n'
                          f'  run: {{base_url: "{URL.replace("127.0.0.1", "localhost")}"}}\n')
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL + "/api"})
    check("a path prefix and another YAML layout do not get past the check", r.returncode == 2 and "REFUSED" in r.stdout
          and sum(SEEN.values()) == sent, r.stdout[-800:])
    w(wb, "sources.yaml", f'reference:\n  run:\n    base_url: "{URL[len("http://"):]}"\n')
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL})
    check("a reference address with no scheme cannot be compared, so it refuses", r.returncode == 2 and "REFUSED" in r.stdout
          and sum(SEEN.values()) == sent, r.stdout[-800:])
    w(wb, "sources.yaml", "reference: [not, a, map\n")
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL})
    check("an unreadable sources.yaml refuses rather than passes", r.returncode == 2 and "REFUSED" in r.stdout
          and "sources.yaml" in r.stdout and sum(SEEN.values()) == sent and "Traceback" not in r.stdout + r.stderr,
          r.stdout[-800:] + r.stderr[-800:])
    w(wb, "sources.yaml", src)
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL})
    check("with the build's URL the boundary runs and names the URL its open suite targets",
          "REFUSED" not in r.stdout and f"target: {URL}" in r.stdout and sum(SEEN.values()) > sent, r.stdout[-1200:])

if ONLY in (None, "equiv"):
    # The smoke run's recorder wrote request headers into committed traces, so a signed-in trace held the token.
    print("\n# equivalence traces never hold a credential (S-38)")
    TOKEN = "s3cret-member-token"
    LEAK = [""]

    class Legacy(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            auth = self.headers.get("Authorization") or ""
            if self.path == "/api/echo":
                status, body = 200, {"you": auth}
            elif self.path == "/api/leak":
                status, body = 200, {"admin": LEAK[0]}
            elif self.path == "/api/names":
                status, body = 200, {"cookies": ["_myapp_session"], "lang": "en"}
            else:
                status, body = (200, {"name": "member"}) if auth == f"Bearer {TOKEN}" else (401, {"error": "sign in"})
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    legacy = socketserver.TCPServer(("127.0.0.1", 0), Legacy)
    threading.Thread(target=legacy.serve_forever, daemon=True).start()
    LURL = f"http://127.0.0.1:{legacy.server_address[1]}"
    proj, wb = project("equiv", split=False)
    src = read(wb, "sources.yaml")
    src = re.sub(r"^(  kind:).*$", r"\1 own-code", src, count=1, flags=re.M)
    w(wb, "sources.yaml", re.sub(r"^(  posture:).*$", r'\1 "own-code"', src, count=1, flags=re.M))
    w(wb, "preflight.json", json.dumps({"checks": [{"id": "instance", "status": "pass"}]}))
    w(wb, "parity/equiv/config.yaml", "adapter: none\nlegacy:\n  base_url_env: EQUIV_LEGACY_URL\n"
                                      "rebuild:\n  base_url_env: EQUIV_REBUILD_URL\n")
    w(wb, "parity/equiv/F-ISS-01/me.request.yaml", "feature: F-ISS-01\nrequest:\n  method: GET\n  path: /api/me\n"
                                                   f"  headers: {{ Authorization: Bearer {TOKEN} }}\n")
    acct = {"ACCEPT_ACCOUNT_MEMBER": f"Authorization: Bearer {TOKEN}"}
    r = script(wb, "equiv.py", "record", "F-ISS-01", env={"EQUIV_LEGACY_URL": LURL, **acct})
    tpath = os.path.join(wb, "parity", "equiv", "F-ISS-01", "me.trace.yaml")
    raw = open(tpath, "rb").read() if os.path.exists(tpath) else b""
    check("a signed-in recording leaves no byte of the token in the trace and names the account",
          r.returncode == 0 and raw and TOKEN.encode() not in raw and b"account: MEMBER" in raw and b"status: 200" in raw,
          r.stdout + r.stderr + raw.decode("utf-8", "replace"))
    r = script(wb, "equiv.py", "replay", "F-ISS-01", env={"EQUIV_REBUILD_URL": LURL, **acct})
    check("…and replays green with the live account re-inserted", r.returncode == 0 and "ok     F-ISS-01 › me" in r.stdout,
          r.stdout + r.stderr)
    r = script(wb, "equiv.py", "replay", "F-ISS-01", env={"EQUIV_REBUILD_URL": LURL})
    check("…and with the account unset it errors naming the variable, never replays unsigned",
          r.returncode != 0 and "ACCEPT_ACCOUNT_MEMBER" in r.stdout, r.stdout + r.stderr)
    w(wb, "parity/equiv/F-ISS-03/cookie.request.yaml", "feature: F-ISS-03\nrequest:\n  method: GET\n  path: /api/me\n"
                                                       "  headers: { Cookie: sid=unnamed-session }\n")
    w(wb, "parity/equiv/F-ISS-03/echo.request.yaml", "feature: F-ISS-03\nrequest:\n  method: GET\n  path: /api/echo\n"
                                                     "  account: MEMBER\n")
    r = script(wb, "equiv.py", "record", "F-ISS-03", env={"EQUIV_LEGACY_URL": LURL, **acct})
    left = [f for f in os.listdir(os.path.join(wb, "parity", "equiv", "F-ISS-03")) if f.endswith(".trace.yaml")]
    check("a credential no account variable holds, or one the response echoes, writes no trace and says why",
          r.returncode == 1 and not left and "Cookie" in r.stderr and "echo" in r.stderr, r.stdout + r.stderr + str(left))
    # The scan covers every account's credential in every string of the trace, compared unescaped: an unsigned
    # request whose response holds another account's token (with a quote and a backslash in it) is refused too.
    admin = {"ACCEPT_ACCOUNT_ADMIN": 'Authorization: Bearer adm"in\\tok-9'}
    LEAK[0] = 'Bearer adm"in\\tok-9'
    w(wb, "parity/equiv/F-ISS-04/leak.request.yaml", "feature: F-ISS-04\nrequest:\n  method: GET\n  path: /api/leak\n")
    r = script(wb, "equiv.py", "record", "F-ISS-04", env={"EQUIV_LEGACY_URL": LURL, **acct, **admin})
    check("an unsigned trace whose response holds another account's escaped token is refused",
          r.returncode == 1 and "ACCEPT_ACCOUNT_ADMIN" in r.stderr
          and not os.path.exists(os.path.join(wb, "parity", "equiv", "F-ISS-04", "leak.trace.yaml")), r.stdout + r.stderr)
    # A signed request may not name its own host: urljoin would send the operator's token there.
    w(wb, "parity/equiv/F-ISS-05/away.request.yaml", "feature: F-ISS-05\nrequest:\n  method: GET\n"
                                                     f"  path: {LURL}/api/me\n  account: MEMBER\n")
    r = script(wb, "equiv.py", "record", "F-ISS-05", env={"EQUIV_LEGACY_URL": LURL, **acct})
    check("a signed request with an absolute path is refused", r.returncode == 1 and "relative" in r.stderr
          and not os.path.exists(os.path.join(wb, "parity", "equiv", "F-ISS-05", "away.trace.yaml")), r.stdout + r.stderr)
    # A tab in the path survives the "starts with one /" check, and urljoin drops it, which makes the rest a host.
    w(wb, "parity/equiv/F-ISS-09/tab.request.yaml", "feature: F-ISS-09\nrequest:\n  method: GET\n"
                                                    f'  path: "/\\t/127.0.0.1:{server.server_address[1]}/api/x"\n  account: MEMBER\n')
    sent = sum(SEEN.values())
    r = script(wb, "equiv.py", "record", "F-ISS-09", env={"EQUIV_LEGACY_URL": LURL, **acct})
    check("a path that urljoin turns into another host is refused, and that host gets nothing", r.returncode == 1
          and sum(SEEN.values()) == sent and not os.path.exists(os.path.join(wb, "parity", "equiv", "F-ISS-09", "tab.trace.yaml")),
          r.stdout + r.stderr)
    # A credential the scan cannot read is a credential it cannot find: refuse, never record unscanned.
    r = script(wb, "equiv.py", "record", "F-ISS-01", "--force", env={"EQUIV_LEGACY_URL": LURL, **acct,
                                                                     "ACCEPT_ACCOUNT_ADMIN": "Bearer no-header-name"})
    check("a malformed ACCEPT_ACCOUNT_ variable refuses the recording, naming it", r.returncode == 1
          and "ACCEPT_ACCOUNT_ADMIN" in r.stderr and "recorded " not in r.stdout, r.stdout + r.stderr)
    # A cookie's name is not its secret: a response naming the cookie records.
    w(wb, "parity/equiv/F-ISS-06/names.request.yaml", "feature: F-ISS-06\nrequest:\n  method: GET\n  path: /api/names\n"
                                                      "  account: COOKIE\n")
    r = script(wb, "equiv.py", "record", "F-ISS-06", env={"EQUIV_LEGACY_URL": LURL,
                                                          "ACCEPT_ACCOUNT_COOKIE": "Cookie: lang=en; _myapp_session=abc123xyz"})
    check("a response that names the account's cookie, or holds a short cookie's value (lang=en), records", r.returncode == 0
          and os.path.exists(os.path.join(wb, "parity", "equiv", "F-ISS-06", "names.trace.yaml")), r.stdout + r.stderr)
    # A replay failure quotes the rebuild's response; the committed JUnit and the console must not carry a token.
    w(wb, "parity/equiv/F-ISS-07/echo.trace.yaml", "feature: F-ISS-07\nrules: []\nrequest:\n  method: GET\n"
                                                   "  path: /api/echo\n  account: MEMBER\nexpect:\n  status: 200\n"
                                                   "  body:\n    you: nobody\nignore: []\ntables: []\n")
    r = script(wb, "equiv.py", "replay", "F-ISS-07", env={"EQUIV_REBUILD_URL": LURL, **acct})
    junit = "".join(read(p) for p in glob.glob(os.path.join(wb, "parity", "*-equiv.xml")))
    check("a replay difference that echoes the token is reported without it", r.returncode == 1
          and "FAIL" in r.stdout and TOKEN not in r.stdout + r.stderr + junit and "you" in junit, r.stdout + junit[-600:])
    # Equivalence is a G6 step too: replaying against the legacy system compares it with itself.
    r = script(wb, "equiv.py", "replay", "F-ISS-01", env={"EQUIV_REBUILD_URL": LURL, "EQUIV_LEGACY_URL": LURL, **acct})
    check("replay refuses a rebuild URL that is the legacy system's", r.returncode == 1 and "legacy" in r.stderr
          and "ok " not in r.stdout, r.stdout + r.stderr)
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL, "EQUIV_REBUILD_URL": LURL, "EQUIV_LEGACY_URL": LURL, **acct})
    check("…and the boundary stops there, not carrying on to step 4", r.returncode == 2 and "Stopped after equivalence" in r.stdout
          and "== 4." not in r.stdout, r.stdout[-1200:])
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL, "EQUIV_REBUILD_URL": LURL, **acct,
                                             "ACCEPT_ACCOUNT_ADMIN": "Bearer no-header-name"})
    check("an unreadable ACCEPT_ACCOUNT_ variable stops the boundary at equivalence too", r.returncode == 2
          and "Stopped after equivalence" in r.stdout and "== 4." not in r.stdout, r.stdout[-1200:])
    # A lane that applies (observe or own-code, the reference runs) but was never set up is not a refusal: G6
    # reports it not run and goes on, or a third-party workbench under observe could never pass step 3.
    cfg_p = os.path.join(wb, "parity", "equiv", "config.yaml")
    os.replace(cfg_p, cfg_p + ".off")
    r = script(wb, "boundary.py", "S1", env={"ACCEPT_BASE_URL": URL, **acct})
    os.replace(cfg_p + ".off", cfg_p)
    check("an equivalence lane that is not set up is reported not run, and the boundary carries on to step 4",
          "not run:" in r.stdout.split("== 3.")[-1].split("== 4.")[0] and "== 4." in r.stdout
          and "Stopped after equivalence" not in r.stdout, r.stdout[-1500:])
    # A trace written before rc.2 can hold a header literally: record and replay say to re-record it.
    w(wb, "parity/equiv/F-ISS-08/old.request.yaml", "feature: F-ISS-08\nrequest:\n  method: GET\n  path: /api/me\n")
    w(wb, "parity/equiv/F-ISS-08/old.trace.yaml", "feature: F-ISS-08\nrules: []\nrequest:\n  method: GET\n  path: /api/me\n"
                                                  f"  headers:\n    Authorization: Bearer {TOKEN}\nexpect:\n  status: 200\n"
                                                  "  body:\n    name: member\nignore: []\ntables: []\n")
    r = script(wb, "equiv.py", "record", "F-ISS-08", env={"EQUIV_LEGACY_URL": LURL, **acct})
    check("an existing trace holding a credential header is named, with the re-record command",
          "old.trace.yaml" in r.stdout + r.stderr and "--force" in r.stdout + r.stderr and "credential" in r.stdout + r.stderr,
          r.stdout + r.stderr)
    legacy.shutdown()

server.shutdown()
shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
