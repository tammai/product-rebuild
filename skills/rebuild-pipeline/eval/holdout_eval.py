#!/usr/bin/env python3
"""holdout_eval.py (eval) — 3.0.0, spec 05 P4 and D4: are the hidden tests chosen as D4 says, kept
out of every code repo, pinned by Gate 4, and run without telling a lane what they expect?

  python3 skills/rebuild-pipeline/eval/holdout_eval.py [split|run]

WHY IT EXISTS. Hidden tests are the one check a builder cannot have tuned the build to: a selection
that varies run to run, a file left in a repo a lane can read, or a failure report that quotes the
expected value would each turn them back into open tests. This scaffolds a workbench with
rebuild_init.py, writes an rspec spec, lock and bundle by hand (no model call), splits, locks Gate 4,
and runs the hidden tests against a local HTTP server. With an argument it runs one group, which is
how the change file's acceptance tests name them. (Named holdout_eval.py so it never shadows the
script it tests.)
"""
from __future__ import annotations

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
ONLY = sys.argv[1] if len(sys.argv) > 1 else None
SECRET = "EXPECTED-VALUE-ONLY-THE-TEST-KNOWS"

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'' if ok or not detail else chr(10) + '      ' + str(detail)}")
    if not ok:
        failures += 1


base = tempfile.mkdtemp(prefix="holdout-eval-")
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


def commit(d):
    run(["git", "add", "-A"], d)
    run(["git", "commit", "-qm", "eval"], d)


# Slice 1: F-ISS-01 (3 criteria, all level 2) and F-ISS-02 (1, level 2). Slice 2: F-PRJ-01 (4 criteria,
# 3 at level 2). D4: ceil(25%) of each slice's level 2 tests, at least 1 per feature with >= 3 criteria.
CRITERIA = [("F-ISS-01", 1, 2), ("F-ISS-01", 2, 2), ("F-ISS-01", 3, 2), ("F-ISS-02", 1, 2),
            ("F-PRJ-01", 1, 2), ("F-PRJ-01", 2, 2), ("F-PRJ-01", 3, 2), ("F-PRJ-01", 4, 1)]


def make_project(name):
    proj = os.path.join(base, name)
    os.makedirs(proj)
    r = run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "p", "--dir", proj], proj)
    check(f"{name}: rebuild_init creates the workbench", r.returncode == 0, r.stderr)
    wb = os.path.join(proj, "p-workbench")
    app = os.path.join(proj, "app")
    os.makedirs(app)
    run(["git", "init", "-q", "-b", "main"], app)
    w(app, "README.md", "# app\n")
    commit(app)
    w(wb, "repos.yaml", "repos:\n  - name: app\n    path: ../app\n")
    w(wb, "docs/rspec.json", json.dumps({"product": "p", "goal": "production", "stage": "handoff", "reference": {"run": {"kind": "http"}}}))
    w(wb, "docs/build-plan.md", "# Build plan\n\n## Slice 1: issues\n\n| 1 | F-ISS-01 a | | | | | |\n| 2 | F-ISS-02 b | | | | | |\n\n"
                                "## Slice 2: projects\n\n| 1 | F-PRJ-01 c | | | | | |\n")
    rows, tests = [], []
    for feat, n, level in CRITERIA:
        cid = f"{feat}.AC{n}"
        path = f"http/{cid}.yaml" if level == 2 else None
        rows.append({"id": cid, "feature": feat, "file": f"features/{feat}.md", "text_sha256": "0" * 64, "tag": "observed",
                     "priority": "MVP", "level": level, "test": f"acceptance/{path}" if path else None, "departures": []})
        if path:
            body = (f"criterion: {cid}\nsteps:\n  - request: {{method: GET, path: /api/{cid}}}\n"
                    f"    expect:\n      status: 200\n      json:\n        - {{pointer: /key, equals: \"{SECRET}\"}}\n")
            w(wb, f"docs/acceptance/{path}", body)
            tests.append({"criterion": cid, "runner": "http", "path": path,
                          "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "level": "integration",
                          "visibility": "open", "recorded_against": {"kind": "oss", "version_or_commit": "v1",
                                                                      "base_url_env": "ACCEPT_BASE_URL"},
                          "last_green": {"timestamp": "2026-11-08T00:00:00Z", "target": "reference"}, "normalize": []})
    w(wb, "docs/criteria.lock.json", json.dumps({"contracts": "1.1.1", "spec": "docs", "generated": "2026-11-08T00:00:00Z",
                                                 "criteria": rows}, indent=2))
    w(wb, "docs/acceptance/manifest.json", json.dumps({"contracts": "1.1.1", "tests": tests}, indent=2))
    for rel in ("docs/features.md", "docs/domain.md", "docs/departures.yaml", "docs/audit/summary.md",
                "docs/verify/summary.md", "docs/openapi.json", "docs/schemas/issue.json"):
        w(wb, rel, "{}\n")
    w(wb, "docs/decisions/0001-stack.md", "# Stack\n\n- Status: Accepted\n")
    src = open(os.path.join(wb, "sources.yaml"), encoding="utf-8").read()
    w(wb, "sources.yaml", re.sub(r"^(  posture:).*$", r'\1 "strict"', src, count=1, flags=re.M))
    commit(wb)
    return proj, wb


def holdout(wb, *a, env=None):
    return run([sys.executable, os.path.join("scripts", "holdout.py"), *a], wb, env)


def record(wb):
    with open(os.path.join(wb, "plan", "holdout.json"), encoding="utf-8") as f:
        return json.load(f)


proj, wb = make_project("main")
pristine = os.path.join(base, "pristine")
shutil.copytree(proj, pristine)
hold = os.path.join(proj, "p-holdout")

if ONLY in (None, "split", "run"):
    print("\n# split (AC-007)")
    for gid in ("gate-1", "gate-3", "gate-2"):
        r = run([sys.executable, os.path.join("scripts", "gate.py"), "lock", gid, "--by", "Eval"], wb)
        check(f"{gid} locks", r.returncode == 0, r.stdout + r.stderr)
    r = run([sys.executable, os.path.join("scripts", "gate.py"), "lock", "gate-4", "--by", "Eval"], wb)
    check("gate-4 refuses before the hidden tests are split out", r.returncode == 1 and "holdout" in r.stderr, r.stderr)
    r = holdout(wb, "split", "--seed", "7")
    check("holdout.py split runs", r.returncode == 0, r.stdout + r.stderr)
    rec = record(wb)
    hidden = rec.get("hidden") or []
    by_slice = {s: [c for c in hidden if c.startswith(p)] for s, p in (("S1", "F-ISS"), ("S2", "F-PRJ"))}
    check("D4: one hidden in slice 1 (ceil 25% of 4), from F-ISS-01, the feature with 3 criteria",
          len(by_slice["S1"]) == 1 and by_slice["S1"][0].startswith("F-ISS-01."), hidden)
    check("D4: one hidden in slice 2 (ceil 25% of 3 level 2 tests), never the level 1 criterion",
          len(by_slice["S2"]) == 1 and by_slice["S2"][0] != "F-PRJ-01.AC4", hidden)
    manifest = json.load(open(os.path.join(wb, "docs", "acceptance", "manifest.json"), encoding="utf-8"))
    vis = {t["criterion"]: t["visibility"] for t in manifest["tests"]}
    check("hidden tests are marked visibility: hidden in the workbench manifest, the rest stay open",
          all(vis[c] == "hidden" for c in hidden) and sum(v == "hidden" for v in vis.values()) == len(hidden), vis)
    tracked = run(["git", "ls-files"], hold).stdout.split()
    check("each hidden file left the workbench bundle and is committed in <project>-holdout/",
          all(not os.path.exists(os.path.join(wb, "docs", "acceptance", "http", f"{c}.yaml")) and f"http/{c}.yaml" in tracked
              for c in hidden), tracked)
    again = os.path.join(base, "again")
    shutil.copytree(pristine, again)
    r = holdout(os.path.join(again, "p-workbench"), "split", "--seed", "7")
    check("the same seed gives the same list", r.returncode == 0 and record(os.path.join(again, "p-workbench"))["hidden"] == hidden,
          r.stdout + r.stderr)
    bad = os.path.join(base, "bad")
    shutil.copytree(pristine, bad)
    w(os.path.join(bad, "app"), ".gitmodules", '[submodule "tests"]\n\tpath = tests\n\turl = ../p-holdout\n')
    commit(os.path.join(bad, "app"))
    r = holdout(os.path.join(bad, "p-workbench"), "split", "--seed", "7")
    check("split refuses when a listed code repo references the holdout repo",
          r.returncode == 1 and "app" in r.stderr and not os.path.exists(os.path.join(bad, "p-holdout")), r.stdout + r.stderr)
    commit(wb)
    r = run([sys.executable, os.path.join("scripts", "gate.py"), "lock", "gate-4", "--by", "Eval"], wb)
    lock4 = open(os.path.join(wb, "locks", "gate-4.yaml"), encoding="utf-8").read()
    check("gate-4 locks after the split and records seed, count and list hash",
          r.returncode == 0 and re.search(r"^holdout:\n  seed: 7\n  count: 2\n  list_sha256: [0-9a-f]{64}$", lock4, re.M)
          is not None, r.stdout + r.stderr + lock4)


class Reference(http.server.BaseHTTPRequestHandler):
    """Answers /api/<criterion>: right for slice 2's criteria, wrong for slice 1's."""

    def do_GET(self):
        key = SECRET if "F-PRJ" in self.path else "WRONG-FROM-THE-BUILD"
        body = json.dumps({"key": key}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if ONLY in (None, "run"):
    print("\n# run (AC-015)")
    server = socketserver.TCPServer(("127.0.0.1", 0), Reference)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    r = holdout(wb, "run", "S1", env={"ACCEPT_BASE_URL": url})
    out = open(os.path.join(wb, "parity", "holdout", "S1.json"), encoding="utf-8").read()
    md = open(os.path.join(wb, "parity", "holdout", "S1.md"), encoding="utf-8").read()
    res = json.loads(out)
    s1 = [c for c in record(wb)["hidden"] if c.startswith("F-ISS")][0]
    row = next((x for x in res["results"] if x["criterion"] == s1), {})
    check("a failing hidden test is reported fail for its criterion, exit 1",
          r.returncode == 1 and row.get("result") == "fail", r.stdout + r.stderr + out)
    check("…with the observed behaviour", "WRONG-FROM-THE-BUILD" in row.get("observed", ""), row)
    check("…and nothing of what the test expects, in the JSON, the Markdown or the console",
          all(SECRET not in t and "expected" not in t for t in (out, md, r.stdout, r.stderr)), out + md + r.stdout)
    r = holdout(wb, "run", "S2", env={"ACCEPT_BASE_URL": url})
    res = json.load(open(os.path.join(wb, "parity", "holdout", "S2.json"), encoding="utf-8"))
    check("a passing hidden test is reported pass, exit 0",
          r.returncode == 0 and [x["result"] for x in res["results"]] == ["pass"], r.stdout + r.stderr)
    r = holdout(wb, "run", "S2", env={"ACCEPT_BASE_URL": ""})
    res = json.load(open(os.path.join(wb, "parity", "holdout", "S2.json"), encoding="utf-8"))
    check("with no target, each test is not run with its reason, never a pass",
          r.returncode == 1 and res["results"][0]["result"] == "not run" and "ACCEPT_BASE_URL" in res["results"][0]["observed"],
          r.stdout + r.stderr)
    server.shutdown()

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
