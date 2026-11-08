#!/usr/bin/env python3
"""lane_plan.py (eval) — 2.0.0, 3.0.0: does the lane-worker agent carry the standing rules a lane brief used to
paste each time, and does routing send build lanes to it and lane reviews to sdlc's reviewers?

  python3 skills/rebuild-pipeline/eval/lane_plan.py [worker|routing|approval]

WHY IT EXISTS. A build lane reads its rules from agents/lane-worker.md and is dispatched on the model
scripts/routing.py names; a rule dropped from the file, or a review routed below the model sdlc accepts, fails
in a lane nobody watches. From 3.0.0 the lanes themselves are opened from rspec's criteria and tested in
lanes_rspec.py; the 2.x `--specs` lanes this eval used to drive are gone. With an argument it runs one group,
which is how docs/MIGRATION-3.md names them.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SCRIPTS = os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts")
ONLY = sys.argv[1] if len(sys.argv) > 1 else None

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


base = tempfile.mkdtemp(prefix="lane-plan-eval-")
# The holdout and its local config go to a per-user data folder; an eval must never write the real one.
os.environ["PRODUCT_REBUILD_DATA"] = os.path.join(base, "user-data")

if ONLY in (None, "worker"):
    print("\n# lane-worker.md carries the standing rules the lane brief used to paste each time")
    worker_md = read(os.path.join(ROOT, "agents", "lane-worker.md"))
    for label, needle in (
            ("the cadence: stamp before the joint run", "lanes_check.py stamp"),
            ("the cadence: rerun only failures", "ONLY\n  the failed specs"),
            ("the cadence: commit before stamping", "Commit before stamping"),
            ("long runs: run_in_background only", "Only `run_in_background: true` is tracked"),
            ("long runs: never nohup", "Never `nohup`"),
            ("long runs: one process for phases", "run_phases.py parity/runs/<local-date>-<label>"),
            ("long runs: skips bound", "no more than 10% skipped"),
            ("migrations: use only your number", "Use only the number"),
            ("migrations: not up on a shared stack", "Never run a migration `up` against a shared stack"),
            ("helpers: own worktree and record", "A helper's worktree needs its own approved sdlc"),
            ("helpers: never copy the record", "Never copy your own record"),
            ("sdlc: the build loop is sdlc's Build", "`## Build (Stage …)` section"),
            ("sdlc: Test is a file path (the spike)", "Test is the test **file path**"),
            ("sdlc: red without the advance to Build (the spike)", "Run only `verify.py red AC-001 AC-002 …`"),
            ("sdlc: stub before red (the spike)", "Create the names a test imports first"),
            ("sdlc: stop after Build, Review is the orchestrator's", "Stop after Build")):
        check(f"lane-worker.md still says: {label}", needle in worker_md)

if ONLY in (None, "routing"):
    print("\n# routing resolves build lanes to this plugin's agent and reviews to sdlc's")

    def route(cfg):
        wb = tempfile.mkdtemp(dir=base)
        if cfg:
            os.makedirs(os.path.join(wb, ".claude"))
            with open(os.path.join(wb, ".claude", "model-routing.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "routing.py"), "--agents", os.path.join(ROOT, "agents")],
                           cwd=wb, capture_output=True, text=True, encoding="utf-8")
        return json.loads(r.stdout)

    out = route(None)
    roles = out["roles"]
    check("the roles are the build lane and sdlc's two lane reviews; the 2.x mining and drafting roles are gone",
          sorted(roles) == ["build-lane", "lane-review", "lane-ui-review"], sorted(roles))
    check("balanced: build-lane is the lane-worker agent on sonnet at high",
          roles["build-lane"]["agent"].endswith(":lane-worker") and roles["build-lane"]["model"] == "sonnet"
          and roles["build-lane"]["effort"] == "high", json.dumps(roles["build-lane"]))
    check("lane-review is sdlc's code-reviewer on opus, lane-ui-review sdlc's ui-reviewer on opus",
          roles["lane-review"]["agent"] == "sdlc:code-reviewer" and roles["lane-review"]["model"] == "opus"
          and roles["lane-ui-review"]["agent"] == "sdlc:ui-reviewer" and roles["lane-ui-review"]["model"] == "opus",
          json.dumps({k: roles[k] for k in ("lane-review", "lane-ui-review")}))
    check("no warning in the default ladder", not out["warnings"], out["warnings"])
    out = route({"profile": "frontier", "models": {"lane-review": "sonnet", "lane-ui-review": "fable"}})
    roles = out["roles"]
    check("frontier: build-lane runs on opus, and its effort stays at the agent file's pin",
          roles["build-lane"]["model"] == "opus" and roles["build-lane"]["effort"] == "high", json.dumps(roles["build-lane"]))
    check("a review cannot be routed below opus (sdlc would deny it), and says so",
          roles["lane-review"]["model"] == "opus" and any("lane-review cannot run on sonnet" in x for x in out["warnings"]),
          json.dumps(out["warnings"]))
    check("a review can be raised to fable", roles["lane-ui-review"]["model"] == "fable")

if ONLY in (None, "approval"):
    print("\n# lane_plan.py writes the approval the spec gate reads")
    sys.path.insert(0, os.path.join(ROOT, "hooks", "scripts"))
    sys.path.insert(0, SCRIPTS)
    import hooklib  # noqa: E402
    import lane_plan  # noqa: E402
    check("lane_plan.py carries the spec gate's approval and amend formats (copied, not imported: change both together)",
          lane_plan.APPROVAL_NOTE.pattern == hooklib.APPROVAL_NOTE.pattern and lane_plan.AMEND_PREFIX == hooklib.AMEND_PREFIX)

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
