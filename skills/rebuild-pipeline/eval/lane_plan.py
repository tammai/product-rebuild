#!/usr/bin/env python3
"""lane_plan.py (eval) — 2.0.0: does lane_plan.py write the sdlc record the spec gate accepts,
refuse what it must, amend without losing a lane's work, and does slice_review notice a lane
editing its own approved criteria?

  python3 skills/rebuild-pipeline/eval/lane_plan.py

Scaffolds a throwaway workbench with rebuild_init.py and a code repo set up for sdlc with a lane
worktree, then runs the REAL scripts (the copies rebuild_init vendored into the workbench) and
sdlc's own state.py (found the way lane_plan.py finds it: needs sdlc installed, or
SDLC_PLUGIN_ROOT). The spec gate's approval format is imported from hooks/scripts/hooklib.py
(APPROVAL_NOTE, AMEND_PREFIX); lane_plan.py is vendored into workbenches and cannot import them,
so this eval is what fails if the two stop agreeing.
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

SDLC = lane_plan.sdlc_root([])
if not SDLC:
    print("FAIL  sdlc is not installed (no sdlc@sdlc in installed_plugins.json, no SDLC_PLUGIN_ROOT): "
          "this eval drives sdlc's own state.py.")
    sys.exit(1)

# What the sdlc under test calls Build, worked out here from its version rather than through
# lane_plan.stage_numbers(), so the eval checks that function instead of repeating it. sdlc 3.0
# renumbered the phases (ADR 0022 in tammai/sdlc). Run this eval with SDLC_PLUGIN_ROOT set to a 2.x
# and to a 3.x checkout: lane_plan.py has to put the lane at Build on both.
with open(os.path.join(SDLC, "plugin.json") if os.path.exists(os.path.join(SDLC, "plugin.json"))
          else os.path.join(SDLC, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
    SDLC_VERSION = json.load(f)["version"]
SDLC3 = int(SDLC_VERSION.split(".")[0]) >= 3
BUILD, PROCESS = (2, 3) if SDLC3 else (4, 2)
print(f"sdlc {SDLC_VERSION} at {SDLC}: Build is Stage {BUILD}, Process: {PROCESS}")

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
w(wb, "docs/features.md", "| ID | Module | Feature | Behaviour | Priority | Reason | Research ID |\n|---|---|---|---|---|---|---|\n"
                          "| F-A-001 | A | Alpha | a | MVP | J1 | R-1 |\n")
w(wb, "docs/build-plan.md", "# Build plan\n\n## Slice 1: One\n\n| 1 | F-A-001 Alpha |\n")
w(wb, "plan/progress.yaml", "slices: { S1: deployed }\nfeatures: { F-A-001: covered }\n")
SPEC_V1 = ("---\ndomains: [billing]\n---\n# Billing\n\nWhat it does.\n\n## Acceptance criteria\n\n"
           "1. A negative amount is rejected with 422. rule_id: R-BILL-001\n2. Totals round half-even to 2 dp.\n")
w(wb, "plan/specs/S1/billing.md", SPEC_V1)
commit_all(wb, "specs approved")

# The code repo, set up for sdlc the minimal way (its config), and the lane's worktree.
app = os.path.join(base, "app")
os.mkdir(app)
sh(app, "git", "init", "-q", "-b", "main")
sh(app, "git", "config", "user.email", "eval@x")
sh(app, "git", "config", "user.name", "Eval Lane")
w(app, "README.md", "app\n")
commit_all(app, "init")
plain_path = os.path.join(base, "app-S1-plain")
sh(app, "git", "worktree", "add", "-q", "-b", "slice/S1-plain", plain_path)
w(app, ".sdlc/config.json", json.dumps({"docs_dir": "docs/sdlc", "commands": {"test": "true"}}))
commit_all(app, "sdlc config")
lane_path = os.path.join(base, "app-S1-api")
sh(app, "git", "worktree", "add", "-q", "-b", "slice/S1-api", lane_path)


def run_script(name, *a):
    return subprocess.run([sys.executable, os.path.join("scripts", name), *a], cwd=wb, capture_output=True,
                          text=True, encoding="utf-8", env={**os.environ, "SDLC_PLUGIN_ROOT": SDLC})


def lane_plan_cli(*a):
    return run_script("lane_plan.py", *a)


def state_py(*a):
    return subprocess.run([sys.executable, os.path.join(SDLC, "scripts", "state.py"), "--root", lane_path, *a],
                          capture_output=True, text=True, encoding="utf-8")


ARGS = ["S1", "api", "--worktree", lane_path, "--specs", "plan/specs/S1/billing.md"]


def record():
    return json.loads(re.sub(r"^#.*\n", "", read(os.path.join(wb, "plan/lane-plans/S1.yaml")), flags=re.M))["lanes"]["api"]


def change_text():
    d = os.path.join(lane_path, "docs", "sdlc", "changes")
    files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    return read(os.path.join(d, files[0])) if files else ""


def state_text():
    d = os.path.join(lane_path, ".sdlc", "state")
    files = sorted(f for f in os.listdir(d) if f.endswith(".md")) if os.path.isdir(d) else []
    return read(os.path.join(d, files[0])) if files else ""


failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


# --- refusals before anything is written -------------------------------------------------------
w(wb, "plan/specs/S1/billing.md", SPEC_V1 + "3. An uncommitted criterion.\n")
r = lane_plan_cli(*ARGS)
check("refuses specs with uncommitted changes", r.returncode == 1 and re.search(r"uncommitted changes", r.stderr), r.stderr)
w(wb, "plan/specs/S1/billing.md", SPEC_V1)

r = lane_plan_cli("S1", "api", "--worktree", app, "--specs", "plan/specs/S1/billing.md")
check("refuses a worktree on the wrong branch", r.returncode == 1 and re.search(r"expected 'slice/S1-api'", r.stderr), r.stderr)
r = lane_plan_cli("S1", "plain", "--worktree", plain_path, "--specs", "plan/specs/S1/billing.md")
check("refuses a repo sdlc has not set up", r.returncode == 1 and re.search(r"not set up for sdlc", r.stderr), r.stderr)
r = lane_plan_cli("S1", "API", "--worktree", lane_path, "--specs", "plan/specs/S1/billing.md")
check("refuses a lane name sdlc would refuse", r.returncode == 1 and re.search(r"lowercase", r.stderr), r.stderr)
check("nothing written by a refusal", not change_text() and not state_text())

# --- the record the gate reads -----------------------------------------------------------------
r = lane_plan_cli(*ARGS)
ch1, st1 = change_text(), state_text()
check("writes the change file and the state file", r.returncode == 0 and ch1 and st1, r.stderr)
with open(os.path.join(SCRIPTS, "lane_plan.py"), encoding="utf-8") as f:
    lane_plan_src = f.read()
check("lane_plan.py carries the approval format the gate reads (change both together)",
      lane_plan.APPROVAL_NOTE.pattern == hooklib.APPROVAL_NOTE.pattern and lane_plan.AMEND_PREFIX == hooklib.AMEND_PREFIX
      and hooklib.APPROVAL_NOTE.pattern in lane_plan_src,
      f"hooklib: {hooklib.APPROVAL_NOTE.pattern!r} {hooklib.AMEND_PREFIX!r}; "
      f"lane_plan: {lane_plan.APPROVAL_NOTE.pattern!r} {lane_plan.AMEND_PREFIX!r}")
appr = hooklib.APPROVAL_NOTE.search(st1)
check("the gate reads an approval for the lane's branch", appr and appr.group(1) == "slice/S1-api", st1)
head = sh(wb, "git", "rev-parse", "--short", "HEAD").strip()
check("the approval names the spec, the workbench commit and the approver",
      re.search(rf"specs plan/specs/S1/billing\.md @ workbench {head}; approved by Eval Approver", st1), st1)
check("the feature is active, at Build, in sdlc's own format",
      re.search(r"^Status: active", st1, re.M) and re.search(rf"^Current: Stage {BUILD} – Build", st1, re.M)
      and re.search(rf"^Process: {PROCESS}", st1, re.M), st1[:600])
check("the Build stage number came from the state file sdlc wrote", lane_plan.stage_numbers(st1).get("Build") == BUILD,
      lane_plan.stage_numbers(st1))
check("the feature name is sdlc's: date, track, lowercase slice, lane",
      re.fullmatch(r"\d{4}-\d\d-\d\d-m-s1-api", record()["feature"]), record()["feature"])
check("one criterion per spec criterion, verbatim, rule_id kept",
      re.search(r"^- \*\*AC-001\*\* — `billing`: A negative amount is rejected with 422\. rule_id: R-BILL-001$", ch1, re.M)
      and re.search(r"^- \*\*AC-002\*\* — `billing`: Totals round half-even to 2 dp\.$", ch1, re.M), ch1)
check("the test cells are the lane's to fill", ch1.count("| TBD | `TBD` |") == 2, ch1)
check("the change file ends in sdlc's `## Review`, empty for Review to fill",
      ch1.rstrip().endswith(lane_plan.REVIEW_PLACEHOLDER[-1]) and ch1.count("## Review") == 1, ch1[-400:])
check("with no --approved-by, the approver falls back to git's user.name and says so",
      "approved by Eval Approver (git user.name; pass --approved-by)" in st1, st1)
import commit_rules  # noqa: E402  (hooks/scripts: the subject rule the commit gate and the git hook apply)
title = ch1.split("\n", 1)[0].lstrip("# ").strip()
check("the change file's title is a Conventional subject (sdlc's ship.py makes it the commit subject)",
      title == "feat(api): rebuild slice S1" and commit_rules.subject_problem(title) is None, title)
check("the task names its criteria and leaves its files to the lane",
      re.search(r"\*\*billing\*\* — AC-001 AC-002", st1) and "`TBD`" in st1, st1)
check("nothing is committed in the code repo", sh(lane_path, "git", "log", "--oneline").count("\n") == 2)
rec1 = record()
check("the record pins the sdlc folder and version that opened the lane",
      rec1.get("sdlc_root") == SDLC and rec1.get("sdlc_version") == SDLC_VERSION, json.dumps(rec1))
check("lane_plan prints the pinned folder for the brief", f"sdlc:        {SDLC} ({SDLC_VERSION})" in r.stdout, r.stdout)
check("recorded with the criteria's hash and the specs' hashes",
      rec1["ac_sha256"] == lane_plan.ac_hash(ch1) and list(rec1["spec_sha256"]) == ["plan/specs/S1/billing.md"], json.dumps(rec1))

# --- never open a second record over an open one ----------------------------------------------
r = lane_plan_cli(*ARGS)
check("refuses a second record for an open lane", r.returncode == 1 and re.search(r"already has an open sdlc feature", r.stderr), r.stderr)

# --- amend: the lane's work kept where the criterion is unchanged ------------------------------
feature = rec1["feature"]
check("the lane can raise an amend: question", state_py("blocker", feature, "raise", "amend: AC-002 rounds per line").returncode == 0)
REVIEW_WRITTEN = "## Review\n\n- **Verdicts:** code-reviewer-r1 PASS\n"
w(lane_path, rec1["change"], ch1.replace("| AC-001 | TBD | `TBD` |", "| AC-001 | tests/test_neg.py | `pytest tests/test_neg.py` |")
  .split("## Review")[0] + REVIEW_WRITTEN)
r = lane_plan_cli(*ARGS, "--amend")
check("--amend without --reason is refused", r.returncode == 1 and re.search(r"needs --reason", r.stderr), r.stderr)
w(wb, "plan/specs/S1/billing.md", SPEC_V1.replace("half-even to 2 dp", "half-even to 2 dp, per line"))
commit_all(wb, "spec amended")
r = lane_plan_cli(*ARGS, "--amend", "--reason", "rounding is per line", "--approved-by", "Ada (relayed by the coordinator)")
ch2, st2 = change_text(), state_text()
check("--amend re-approves", r.returncode == 0 and len(hooklib.APPROVAL_NOTE.findall(st2)) == 2, r.stderr + st2)
check("an unchanged criterion keeps its id and its test", "| AC-001 | tests/test_neg.py | `pytest tests/test_neg.py` |" in ch2, ch2)
check("a changed criterion takes a new id and starts at TBD",
      re.search(r"^- \*\*AC-003\*\* — `billing`: Totals round half-even to 2 dp, per line\.$", ch2, re.M)
      and "| AC-003 | TBD | `TBD` |" in ch2 and "AC-002" not in ch2.split("## Amendments")[0], ch2)
check("the amendment is logged", re.search(r"^- .*rounding is per line \(criteria added 1, dropped 1\)$", ch2, re.M), ch2)
check("--approved-by names the approver as given", "Ada (relayed by the coordinator): rounding is per line" in ch2, ch2)
check("an amendment keeps what Review wrote, still last",
      ch2.rstrip().endswith("- **Verdicts:** code-reviewer-r1 PASS") and ch2.count("## Review") == 1, ch2[-400:])
check("the lane's amend: question is resolved", "amend:" not in st2.split("## Open questions")[-1], st2.split("## Open questions")[-1])
check("the record counts the amendment", record()["amendments"] == 1)
check("an amendment keeps the sdlc folder the lane was opened with", record().get("sdlc_root") == SDLC, record().get("sdlc_root"))


# --- slice-review sees a lane editing its own approved criteria --------------------------------
def review():
    run_script("slice_review.py", "S1")
    return read(os.path.join(wb, "plan/slice-reviews/S1.md"))


sr = review()
check("slice-review lists the lane's sdlc record", re.search(rf"- api: sdlc `.*-m-s1-api` · Status: active · Stage {BUILD} – Build · 1/2 criteria with a named test", sr), sr[:1200])
check("an untouched record raises nothing about criteria", not re.search(r"no longer matches what lane_plan\.py wrote", sr))
check("a lane sdlc has not shipped is pressed", re.search(rf"api's sdlc feature is `Status: active` at Stage {BUILD} – Build", sr), sr[:1500])
w(lane_path, record()["change"], ch2.replace("rejected with 422", "rejected with 400"))
sr = review()
check("a hand-edited criterion is named in the review", re.search(r"no longer matches what lane_plan\.py wrote", sr), sr[:1500])
state_py("blocker", feature, "raise", "amend: something else")
sr = review()
check("an open amend: question is named in the review", re.search(r"api raised an `amend:` question", sr), sr[:1500])
state_py("blocker", feature, "resolve", "amend: something else")


# --- archive: only a lane sdlc shipped ---------------------------------------------------------
def arch():
    return run_script("lane_plan.py", "archive", "S1", "api")


r = arch()
check("archive refuses a lane sdlc has not shipped", r.returncode == 1 and re.search(r"Status: active", r.stderr), r.stderr)
check("sdlc ships the lane (Status: done)", state_py("set", feature, "Status", "done").returncode == 0)
r = arch()
rec2 = record()
archived = rec2.get("archived") or {}
check("archive copies the record to the workbench and warns about an edited criterion",
      r.returncode == 0 and os.path.exists(os.path.join(wb, archived.get("change", "-")))
      and os.path.exists(os.path.join(wb, archived.get("state", "-")))
      and re.search(r"WARNING: its acceptance criteria differ", r.stdout), r.stdout + r.stderr)
check("the archive is recorded, with the edit flagged", archived.get("ac_edited") is True, json.dumps(archived))
check("the record stays in the code repo (sdlc keeps it)", os.path.exists(os.path.join(lane_path, rec2["change"])))
sr = review()
check("slice-review reads the lane from its archive, and names the edited criterion",
      re.search(r"- api: sdlc `.*` · Status: done", sr) and re.search(r"no longer matches what lane_plan\.py wrote", sr), sr[:1500])
r = arch()
check("a lane is archived once", r.returncode == 1 and re.search(r"already archived", r.stderr), r.stderr)


# --- lane-worker.md carries the standing rules the lane brief used to paste each time -----------
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
        ("sdlc: stop after Build, Review is the orchestrator's", "Stop after Build"),
        ("sdlc: amend through a blocker", 'blocker <feature> raise "amend:')):
    check(f"lane-worker.md still says: {label}", needle in worker_md)
briefs_md = read(os.path.join(ROOT, "skills", "rebuild-pipeline", "references", "subagent-briefs.md"))
check("the build-lane brief no longer pastes the long-run rules", "Never `nohup`" not in briefs_md)


# --- boundary.py: the slice boundary's mechanical steps in one call ------------------------------
def boundary(*a):
    return run_script("boundary.py", *a)


src_path = os.path.join(wb, "sources.yaml")
src_before = read(src_path) if os.path.exists(src_path) else ""
w(wb, "sources.yaml", "reference:\n  kind: third-party\n  upstream: active\n")
r = boundary("S1")
# 3.0.0: boundary.py is G6's sequencer (05 P6); it still archives the lanes and runs parity and the slice review,
# and the 2.x re-mine line is information that never holds a boundary (eval/g6_eval.py tests the sequence).
check("boundary archives the lanes, runs parity and the slice review, and prints the re-mine status",
      all(h in r.stdout for h in ("== 0. S1: archive lane records (1 recorded)", "api: already archived", "coverage: parity",
                                  "regression: slice review"))
      and os.path.exists(os.path.join(wb, "parity")) and "Upstream re-mine: DUE. None is recorded" in r.stdout, r.stdout[:1500] + r.stderr)
check("without the G6 conditions met the boundary is not passed (exit 2)", r.returncode == 2, r.returncode)
check("remine-done records today's date", boundary("remine-done").returncode == 0
      and re.fullmatch(r"\d{4}-\d\d-\d\d\n", read(os.path.join(wb, "parity/last-remine"))) is not None)
r = boundary("S1")
check("a recorded re-mine is not due", "Upstream re-mine: not due. Last on" in r.stdout, r.stdout[-400:] + r.stderr)
w(wb, "parity/last-remine", "2020-01-01\n")
r = boundary("S1")
check("a 30-day-old re-mine is due again", re.search(r"DUE\. Last on 2020-01-01, \d+ days ago", r.stdout), r.stdout[-300:])
w(wb, "sources.yaml", "reference:\n  kind: own-code\n  upstream: frozen   # replaced app\n")
r = boundary("S1")
check("a frozen reference says so", "reference is frozen, no re-mine" in r.stdout, r.stdout[-300:] + r.stderr)
recp = os.path.join(wb, "plan/lane-plans/S1.yaml")
rec3 = json.loads(re.sub(r"^#.*\n", "", read(recp), flags=re.M))
rec3["lanes"]["ghost"] = {"worktree": os.path.join(base, "no-such-worktree")}
w(wb, "plan/lane-plans/S1.yaml", "# test\n" + json.dumps(rec3))
r = boundary("S1")
check("a lane that cannot be archived is named, and the call exits 2", r.returncode == 2 and re.search(r"ghost: NOT archived", r.stdout), r.stdout[:600])
check("boundary with no slice id prints usage", boundary().returncode == 1)
if src_before:
    w(wb, "sources.yaml", src_before)


# --- routing resolves build lanes to this plugin's agent and reviews to sdlc's ------------------
def route(cfg):
    if cfg:
        w(wb, ".claude/model-routing.json", json.dumps(cfg))
    return json.loads(run_script("routing.py", "--agents", os.path.join(ROOT, "agents")).stdout)


out = route(None)
roles = out["roles"]
check("balanced: build-lane is the lane-worker agent on sonnet at high",
      re.search(r"^[\w-]+:lane-worker$", roles["build-lane"].get("agent", "")) and roles["build-lane"]["model"] == "sonnet"
      and roles["build-lane"]["effort"] == "high", json.dumps(roles["build-lane"]))
check("lane-verifier is gone", "lane-verifier" not in roles)
check("lane-review is sdlc's code-reviewer on opus, lane-ui-review sdlc's ui-reviewer on opus",
      roles["lane-review"]["agent"] == "sdlc:code-reviewer" and roles["lane-review"]["model"] == "opus"
      and roles["lane-ui-review"]["agent"] == "sdlc:ui-reviewer" and roles["lane-ui-review"]["model"] == "opus",
      json.dumps({k: roles[k] for k in ("lane-review", "lane-ui-review")}))
check("no warning about sdlc's agents having no file here", not any("lane-review" in x for x in out["warnings"]), out["warnings"])
check("no role resolves to bigin's agents", all(not x["agent"].startswith("bigin") for x in roles.values()))
out = route({"profile": "frontier", "models": {"lane-review": "sonnet", "lane-ui-review": "fable"}})
roles = out["roles"]
check("frontier: build-lane runs on opus, and its effort stays at the agent file's pin",
      roles["build-lane"]["model"] == "opus" and roles["build-lane"]["effort"] == "high", json.dumps(roles["build-lane"]))
check("a review cannot be routed below opus (sdlc would deny it), and says so",
      roles["lane-review"]["model"] == "opus" and any("lane-review cannot run on sonnet" in x for x in out["warnings"]),
      json.dumps(out["warnings"]))
check("a review can be raised to fable", roles["lane-ui-review"]["model"] == "fable")
check("every agent of this plugin a role names is a file in agents/",
      all(os.path.exists(os.path.join(ROOT, "agents", x["agent"].split(":")[1] + ".md"))
          for x in roles.values() if not x["agent"].startswith("sdlc:")))

shutil.rmtree(base, ignore_errors=True) if not failures else None
print(f"\n{failures} failure(s). Workbench left at {base}" if failures else "\nall passed")
sys.exit(1 if failures else 0)
