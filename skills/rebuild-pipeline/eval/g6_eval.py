#!/usr/bin/env python3
"""g6_eval.py (eval) — 3.0.0, spec 05 P6 and P7: does a slice boundary run G6 cheapest first and stop at the
first fix it needs, does every finding go where contracts C6 says, does the human sample become findings,
and does one departures registry explain differences everywhere?

  python3 skills/rebuild-pipeline/eval/g6_eval.py [route|boundary|sample|departures|fix|remine]

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
    r2 = script(wb, "route.py", "S1")
    check("a second run is round 2", r2.returncode == 0 and os.path.exists(os.path.join(wb, "plan", "fix-rounds", "S1-r2.md")),
          r2.stdout + r2.stderr)
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
    check("an open Playwright test with no lane JUnit is not run, and the boundary does not pass",
          rc == 2 and "F-ISS-03.AC1: not run: no lane JUnit" in out, out)
    import time
    w(proj, f"app/parity/{time.strftime('%Y-%m-%d')}-ac.xml",
      '<testsuite><testcase classname="e2e" name="F-ISS-03.AC1 shows the total"/></testsuite>\n')
    rc, out = boundary()
    check("…read from the lanes' JUnit in the code repo, a passing case for it lets the boundary pass", rc == 0 and "PASS" in out, out)
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
    for gid in ("gate-1",):
        commit(wb)
        rr = script(wb, "gate.py", "lock", gid, "--by", "Eval")
    before = read(wb, "docs", "departures.yaml")
    r = script(wb, "flows.py", "unlock", "--acceptance", "--weakens", "--criteria", "F-ISS-03.AC1", "--by", "Tam Mai",
               "--reason", "another")
    check("while gate-1 hashes departures.yaml, adding a departure after its lock is refused, nothing written",
          rr.returncode == 0 and r.returncode == 1 and "gate-1" in r.stderr and read(wb, "docs", "departures.yaml") == before,
          rr.stdout + rr.stderr + r.stdout + r.stderr)

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

server.shutdown()
shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
