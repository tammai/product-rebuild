#!/usr/bin/env python3
"""lane_plan.py (eval) — E17b, 0.29.0: does lane_plan.py write a PLAN.md the plugin's spec gate
accepts, refuse what it must, amend without losing progress, and does slice_review notice a
lane editing its own approved spec?

  python3 skills/rebuild-pipeline/eval/lane_plan.py

Scaffolds a throwaway workbench with rebuild_init.py and a code repo with a lane worktree, then
runs the REAL scripts (the copies rebuild_init vendored into the workbench) and asserts on the
files they write. The spec gate's two patterns are imported from hooks/scripts/hooklib.py
(PLAN_STATUS, PLAN_BRANCH), the same ones spec_gate_guard.py reads; lane_plan.py is vendored
into workbenches and cannot import them, so this eval is what fails if the two stop agreeing.
Needs no node and no install step: the scripts are standard-library Python.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCRIPTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "scripts")
ROOT = os.path.realpath(os.path.join(SCRIPTS, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "hooks", "scripts"))
sys.path.insert(0, os.path.realpath(SCRIPTS))
import hooklib  # noqa: E402
import lane_plan  # noqa: E402

GUARD_STATUS, GUARD_BRANCH = hooklib.PLAN_STATUS, hooklib.PLAN_BRANCH

base = tempfile.mkdtemp(prefix="lane-plan-eval-")
subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "lp", "--dir", base],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
wb = os.path.join(base, "lp-workbench")


def sh(cwd, *cmd):
    return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True).stdout


GIT_ID = ["-c", "user.email=eval@x", "-c", "user.name=Eval Approver"]


def commit_all(cwd, msg):
    sh(cwd, "git", "add", "-A")
    sh(cwd, "git", *GIT_ID, "commit", "-qm", msg)


def w(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()


# The workbench as a git repo with an identity, as a real one is.
if not os.path.exists(os.path.join(wb, ".git")):
    sh(wb, "git", "init", "-q")  # rebuild_init normally has
sh(wb, "git", "config", "user.name", "Eval Approver")
sh(wb, "git", "config", "user.email", "eval@x")
w(wb, "matrix/features.yaml", "- id: F-A-001\n  name: Alpha\n  domain: billing\n  confidence: high\n")
w(wb, "plan/slices.yaml", "- id: S1\n  name: One\n  features: [F-A-001]\n")
w(wb, "plan/progress.yaml", "slices: { S1: deployed }\nfeatures: { F-A-001: covered }\n")
SPEC_V1 = ("---\ndomains: [billing]\n---\n# Billing\n\nWhat it does.\n\n## Acceptance criteria\n\n"
           "1. A negative amount is rejected with 422. rule_id: R-BILL-001\n2. Totals round half-even to 2 dp.\n")
w(wb, "plan/specs/S1/billing.md", SPEC_V1)
commit_all(wb, "specs approved")

# The code repo and the lane's worktree.
app = os.path.join(base, "app")
os.mkdir(app)
sh(app, "git", "init", "-q", "-b", "main")
w(app, "README.md", "app\n")
commit_all(app, "init")
lane_path = os.path.join(base, "app-S1-api")
sh(app, "git", "worktree", "add", "-q", "-b", "slice/S1-api", lane_path)


def run_script(name, *a):
    return subprocess.run([sys.executable, os.path.join("scripts", name), *a], cwd=wb, capture_output=True,
                          text=True, encoding="utf-8")


def lane_plan_cli(*a):
    return run_script("lane_plan.py", *a)


ARGS = ["S1", "api", "--worktree", lane_path, "--specs", "plan/specs/S1/billing.md"]


def plan_text():
    p = os.path.join(lane_path, "PLAN.md")
    return read(p) if os.path.exists(p) else ""


failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


def group1(rx, text):
    m = rx.search(text)
    return m.group(1) if m else None


# --- refusals before anything is written -------------------------------------------------------
w(wb, "plan/specs/S1/billing.md", SPEC_V1 + "3. An uncommitted criterion.\n")
r = lane_plan_cli(*ARGS)
check("refuses specs with uncommitted changes", r.returncode == 1 and re.search(r"uncommitted changes", r.stderr), r.stderr)
w(wb, "plan/specs/S1/billing.md", SPEC_V1)

r = lane_plan_cli("S1", "api", "--worktree", app, "--specs", "plan/specs/S1/billing.md")
check("refuses a worktree on the wrong branch", r.returncode == 1 and re.search(r"expected 'slice/S1-api'", r.stderr), r.stderr)
check("nothing written by a refusal", not plan_text())

# --- the plan the gate reads -------------------------------------------------------------------
r = lane_plan_cli(*ARGS)
plan1 = plan_text()
check("writes PLAN.md", r.returncode == 0 and plan1, r.stderr)
with open(os.path.join(SCRIPTS, "lane_plan.py"), encoding="utf-8") as f:
    lane_plan_src = f.read()
check("lane_plan.py carries the same Status:/Branch: patterns the gate reads (change both together)",
      GUARD_STATUS.pattern in lane_plan_src and GUARD_BRANCH.pattern in lane_plan_src
      and lane_plan.PLAN_STATUS.pattern == GUARD_STATUS.pattern and lane_plan.PLAN_STATUS.flags == GUARD_STATUS.flags
      and lane_plan.PLAN_BRANCH.pattern == GUARD_BRANCH.pattern and lane_plan.PLAN_BRANCH.flags == GUARD_BRANCH.flags,
      f"hooklib: {GUARD_STATUS.pattern!r} {GUARD_BRANCH.pattern!r}; lane_plan: {lane_plan.PLAN_STATUS.pattern!r} {lane_plan.PLAN_BRANCH.pattern!r}")
check("the spec gate reads Status: approved", (group1(GUARD_STATUS, plan1) or "").lower() == "approved")
check("the spec gate reads the lane's branch", group1(GUARD_BRANCH, plan1) == "slice/S1-api")
head = sh(wb, "git", "rev-parse", "--short", "HEAD").strip()
check("Approved: names the spec, the workbench commit and the approver",
      re.search(rf"^Approved: plan/specs/S1/billing\.md @ workbench {head} — Eval Approver, ", plan1, re.M),
      "\n".join(plan1.split("\n")[:6]))
rows1 = [l for l in plan1.split("\n") if re.match(r"^\|\s*\d+\s*\|", l)]
check("one task row per acceptance criterion", len(rows1) == 2, "\n".join(rows1))
check("rule_id carried into its row", re.search(r"\| 1 \| billing AC1: .*rule_id: R-BILL-001 \| Not started \|", plan1))
check("spec headings demoted, so ## Tasks is the only h2 after ## Spec",
      not re.search(r"^## Acceptance criteria", plan1, re.M) and re.search(r"^#### Acceptance criteria", plan1, re.M))
check("recorded in plan/lane-plans/S1.yaml", os.path.exists(os.path.join(wb, "plan/lane-plans/S1.yaml")))

# --- never overwrite unfinished work -----------------------------------------------------------
r = lane_plan_cli(*ARGS)
check("refuses to overwrite a plan with unfinished rows", r.returncode == 1 and re.search(r"unfinished rows", r.stderr), r.stderr)

# --- amend: progress kept where the criterion is unchanged -------------------------------------
w(lane_path, "PLAN.md", re.sub(r"^Status: approved$", "Status: amending",
                               re.sub(r"^(\| 1 \|.*\|) Not started \|", r"\1 Done |", plan1, count=1, flags=re.M),
                               count=1, flags=re.M))
r = lane_plan_cli(*ARGS, "--amend")
check("--amend without --reason is refused", r.returncode == 1 and re.search(r"needs --reason", r.stderr), r.stderr)
w(wb, "plan/specs/S1/billing.md", SPEC_V1.replace("half-even to 2 dp", "half-even to 2 dp, per line"))
commit_all(wb, "spec amended")
r = lane_plan_cli(*ARGS, "--amend", "--reason", "rounding is per line")
plan2 = plan_text()
check("--amend re-approves", r.returncode == 0 and group1(GUARD_STATUS, plan2) == "approved", r.stderr)
check("an unchanged criterion keeps Done", re.search(r"\| 1 \| billing AC1: .* \| Done \|", plan2), plan2)
check("a changed criterion goes back to Not started", re.search(r"\| 2 \| billing AC2: .*per line\. \| Not started \|", plan2))
check("the amendment is logged",
      re.search(r"^## Amendments\n\n- .*rounding is per line \(rows added 1, dropped 1\)$", plan2, re.M),
      plan2.split("## Amendments")[-1])


# --- slice-review sees a lane editing its own approved spec ------------------------------------
def review():
    run_script("slice_review.py", "S1")
    return read(os.path.join(wb, "plan/slice-reviews/S1.md"))


sr = review()
check("slice-review lists the lane plan", re.search(r"- api: 1/2 task rows Done · Status: approved", sr), sr[:900])
check("an untouched spec raises nothing", not re.search(r"no longer matches what lane_plan\.py wrote", sr))
w(lane_path, "PLAN.md", plan2.replace("rejected with 422", "rejected with 400"))
sr = review()
check("a hand-edited ## Spec is named in the review", re.search(r"no longer matches what lane_plan\.py wrote", sr), sr[:1200])


# --- E18: verifier rounds recorded, capped, and surfaced -----------------------------------------
def rv(*a):
    return run_script("lane_plan.py", "record-verify", "S1", "api", *a)


w(lane_path, "PLAN.md", plan2)  # undo the hand-edit above
sr = review()
check("a lane with no verifier round is named",
      re.search(r"- api: .*no verifier round recorded", sr) and re.search(r"api has no recorded verifier PASS", sr), sr[:1400])
r = rv("--verdict", "FAIL", "--round", "2")
check("record-verify refuses a round out of order", r.returncode == 1 and re.search(r"out of order", r.stderr), r.stderr)
check("round 1 FAIL recorded", rv("--verdict", "FAIL", "--round", "1", "--issues", "2").returncode == 0)
check("round 2 FAIL recorded", rv("--verdict", "FAIL", "--round", "2", "--issues", "1").returncode == 0)
r = rv("--verdict", "FAIL", "--round", "3", "--issues", "1")
check("the third FAIL says HALT", r.returncode == 0 and re.search(r"cap reached\. HALT", r.stdout), r.stdout + r.stderr)
r = rv("--verdict", "PASS", "--round", "4")
check("a fourth round is refused", r.returncode == 1 and re.search(r"past the cap", r.stderr), r.stderr)
sr = review()
check("the review shows the last verdict", re.search(r"verifier FAIL at round 3/3", sr), sr[:1400])
r = lane_plan_cli(*ARGS, "--amend", "--reason", "plan was wrong")
rec = json.loads(re.sub(r"^#.*\n", "", read(os.path.join(wb, "plan/lane-plans/S1.yaml")), flags=re.M))
check("an amended plan restarts the count and keeps prior rounds",
      r.returncode == 0 and len(rec["lanes"]["api"]["verify"]) == 0 and len(rec["lanes"]["api"].get("verify_prior") or []) == 3,
      json.dumps(rec["lanes"]["api"]))
ok_round1 = rv("--verdict", "PASS", "--round", "1").returncode == 0
sr_after = review()
check("round 1 after an amendment is accepted, and PASS clears the review",
      ok_round1 and re.search(r"verifier PASS at round 1/3", sr_after) and not re.search(r"has no recorded verifier PASS", sr_after))


# --- archive: the plan leaves the worktree at slice end ------------------------------------------
def arch():
    return run_script("lane_plan.py", "archive", "S1", "api")


live = plan_text()
w(lane_path, "PLAN.md", re.sub(r"^(\| 1 \|.*\|) Not started \|", r"\1 Done |", live.replace("| Done |", "| Not started |"),
                               count=1, flags=re.M))
r = arch()
check("archive refuses a plan with unfinished rows", r.returncode == 1 and re.search(r"not Done", r.stderr), r.stderr)
w(lane_path, "PLAN.md", live.replace("rejected with 422", "rejected with 400").replace("| Not started |", "| Done |"))
r = arch()
check("archive moves the plan to the workbench and warns about an edited spec",
      r.returncode == 0 and not plan_text() and os.path.exists(os.path.join(wb, "plan/lane-plans/archive/S1-api.md"))
      and re.search(r"WARNING: the plan's ## Spec differs", r.stdout), r.stdout + r.stderr)
rec2 = json.loads(re.sub(r"^#.*\n", "", read(os.path.join(wb, "plan/lane-plans/S1.yaml")), flags=re.M))
archived = rec2["lanes"]["api"].get("archived") or {}
check("the archive is recorded, with the edit flagged",
      archived.get("path") == "plan/lane-plans/archive/S1-api.md" and archived.get("spec_edited") is True, json.dumps(archived))
sr = review()
check("slice-review still sees the lane from its archive, and names the edited spec",
      re.search(r"- api: 2/2 task rows Done", sr) and re.search(r"no longer matches what lane_plan\.py wrote", sr), sr[:1400])
r = arch()
check("a lane is archived once", r.returncode == 1 and re.search(r"already archived", r.stderr), r.stderr)


# --- routing resolves build lanes to this plugin's agents -----------------------------------------
def route(cfg):
    if cfg:
        w(wb, ".claude/model-routing.json", json.dumps(cfg))
    return json.loads(run_script("routing.py", "--agents", os.path.join(ROOT, "agents")).stdout)["roles"]


roles = route(None)
check("balanced: build-lane is the lane-worker agent on sonnet at high",
      re.search(r"^[\w-]+:lane-worker$", roles["build-lane"].get("agent", "")) and roles["build-lane"]["model"] == "sonnet"
      and roles["build-lane"]["effort"] == "high", json.dumps(roles["build-lane"]))
check("balanced: lane-verifier is the lane-verifier agent",
      re.search(r"^[\w-]+:lane-verifier$", roles["lane-verifier"].get("agent", "")) and roles["lane-verifier"]["effort"] == "high")
check("no role resolves to another plugin's agent",
      all(re.search(r"^[\w-]+:[\w-]+$", x["agent"]) and not x["agent"].startswith("bigin") for x in roles.values()))
roles = route({"profile": "frontier", "models": {"lane-verifier": "opus"}})
check("frontier: build-lane runs on opus, and its effort stays at the agent file's pin",
      roles["build-lane"]["model"] == "opus" and roles["build-lane"]["effort"] == "high", json.dumps(roles["build-lane"]))
check("a lane-verifier role override applies",
      roles["lane-verifier"]["model"] == "opus" and roles["lane-verifier"]["modelFrom"] == "override:role:lane-verifier")
check("every agent a role names is a file in agents/",
      all(os.path.exists(os.path.join(ROOT, "agents", x["agent"].split(":")[1] + ".md")) for x in roles.values()))

shutil.rmtree(base, ignore_errors=True) if not failures else None
print(f"\n{failures} failure(s). Workbench left at {base}" if failures else "\nall passed")
sys.exit(1 if failures else 0)
