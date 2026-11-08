#!/usr/bin/env python3
"""lanes_rspec.py (eval) — 3.0.0, spec 05 P5: does a lane get exactly its criteria and its open tests,
does step 0 hold a slice whose criteria have no recorded test, do spec questions reach one batch, and
does the flow guard keep the recorded bundle read-only?

  python3 skills/rebuild-pipeline/eval/lanes_rspec.py [lane|step0|questions|flows|archive]

WHY IT EXISTS. sdlc 3.5 builds spec-backed only from what is inside the code repo (config `spec_lock`,
`acceptance/manifest.json`), and the rebuild's lock and bundle live in the workbench. lane_plan.py is
the bridge, so a wrong copy here is a lane building against tests nobody recorded, or seeing hidden
ones. sdlc is replaced by a stub `state.py` that records its arguments (the boundary this eval does
not test; eval/lane_plan.py drives the real one). With an argument it runs one group, which is how the
change file's acceptance tests name them.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SCRIPTS = os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts")
HOOKS = os.path.join(ROOT, "hooks", "scripts")
ONLY = sys.argv[1] if len(sys.argv) > 1 else None

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'' if ok or not detail else chr(10) + '      ' + str(detail)}")
    if not ok:
        failures += 1


base = tempfile.mkdtemp(prefix="lanes-rspec-eval-")
STUB = os.path.join(base, "sdlc-stub")
ENV = {"GIT_AUTHOR_NAME": "Eval", "GIT_AUTHOR_EMAIL": "eval@x", "GIT_COMMITTER_NAME": "Eval",
       "GIT_COMMITTER_EMAIL": "eval@x", "SDLC_PLUGIN_ROOT": STUB, "RSPEC_PLUGIN_ROOT": os.path.join(base, "no-rspec")}


def run(cmd, cwd, env=None, stdin=None):
    return subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True, encoding="utf-8",
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


# sdlc's state.py at the boundary: `new` writes a 3.x state file and every call is recorded.
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
                                         "- [ ] 2 Build\n- [ ] 3 Review\n- [ ] 4 Ship\n\n## Open questions\n-\n" % cmd[1])
    print(json.dumps({"ok": True, "event": {"state": ".sdlc/state/%s.md" % cmd[1]}}))
else:
    print(json.dumps({"ok": True}))
''')
w(STUB, ".claude-plugin/plugin.json", '{"version": "3.5.0-rc.6"}')

proj = os.path.join(base, "proj")
os.makedirs(proj)
r = run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "p", "--dir", proj], proj)
check("rebuild_init creates the workbench", r.returncode == 0, r.stderr)
wb = os.path.join(proj, "p-workbench")
app = os.path.join(proj, "app")
lane = os.path.join(proj, "app-lane")
os.makedirs(app)
run(["git", "init", "-q", "-b", "main"], app)
w(app, ".sdlc/config.json", '{"docs_dir": "docs/sdlc"}\n')
w(app, ".gitmodules", '[submodule "workbench"]\n\tpath = workbench\n\turl = ../p-workbench\n')
commit(app)
run(["git", "worktree", "add", "-q", "-b", "slice/S1-api", lane], app)
w(wb, "repos.yaml", "repos:\n  - name: app\n    path: ../app\n")

# Slice 1: F-ISS-01 (3 criteria at level 2; AC3's test is hidden) and F-ISS-02 (level 1, rspec says why).
# Slice 2: F-PRJ-01 (level 1 with no reason: step 0 must hold the slice).
w(wb, "docs/build-plan.md", "# Build plan\n\n## Slice 1: issues\n\n| 1 | F-ISS-01 a | | | | | |\n| 2 | F-ISS-02 b | | | | | |\n\n"
                            "## Slice 2: projects\n\n| 1 | F-PRJ-01 c | | | | | |\n")
rows, tests = [], []
for feat, n, level, vis in (("F-ISS-01", 1, 2, "open"), ("F-ISS-01", 2, 2, "open"), ("F-ISS-01", 3, 2, "hidden"),
                            ("F-ISS-02", 1, 1, None), ("F-PRJ-01", 1, 1, None)):
    cid = f"{feat}.AC{n}"
    path = f"http/{cid}.yaml" if vis else None
    rows.append({"id": cid, "feature": feat, "file": f"features/{feat}.md", "text_sha256": "0" * 64, "tag": "observed",
                 "priority": "MVP", "level": level, "test": f"acceptance/{path}" if path else None, "departures": []})
    if path:
        body = f"criterion: {cid}\nseed: [seed/base.yaml]\nsteps:\n  - request: {{method: GET, path: /x}}\n    expect: {{status: 200}}\n"
        if vis == "open":
            w(wb, f"docs/acceptance/{path}", body)
        tests.append({"criterion": cid, "runner": "http", "path": path, "sha256": hashlib.sha256(body.encode()).hexdigest(),
                      "level": "integration", "visibility": vis, "normalize": []})
w(wb, "docs/acceptance/seed/base.yaml", "steps: []\n")
w(wb, "docs/features.md", "# Features\n")
LOCK = {"contracts": "1.1.1", "spec": "docs", "generated": "2026-11-08T00:00:00Z", "criteria": rows}
w(wb, "docs/criteria.lock.json", json.dumps(LOCK, indent=2))
w(wb, "docs/acceptance/manifest.json", json.dumps({"contracts": "1.1.1", "tests": tests}, indent=2))
w(wb, "docs/verify/outcomes.jsonl", json.dumps({"criterion": "F-ISS-02.AC1", "outcome": "unrecordable",
                                                "reason": "needs a paid plan"}) + "\n")
# This bundle stands for one after holdout.py split (AC-3's test is already out), which un-ignores it.
w(wb, ".gitignore", "".join(l for l in open(os.path.join(wb, ".gitignore"), encoding="utf-8").readlines()
                            if l.rstrip("\n") != "docs/acceptance/" and "holdout.py split" not in l and "this repo's history" not in l))
commit(wb)


def lane_plan(*a):
    return run([sys.executable, os.path.join("scripts", "lane_plan.py"), *a], wb)


if ONLY in (None, "lane", "questions"):
    print("\n# a lane's criteria and open bundle (AC-016)")
    r = lane_plan("S1", "api", "--worktree", "../app-lane", "--features", "F-ISS-01", "--approved-by", "Eval")
    check("lane_plan opens the lane from the slice's features", r.returncode == 0, r.stdout + r.stderr)
    changes = [f for f in os.listdir(os.path.join(lane, "docs", "sdlc", "changes"))] if os.path.isdir(
        os.path.join(lane, "docs", "sdlc", "changes")) else []
    change = read(lane, "docs", "sdlc", "changes", changes[0]) if changes else ""
    check("the change file cites each criterion by ID, without restating it",
          all(f"- **AC-00{i}** → F-ISS-01.AC{i}" in change for i in (1, 2, 3)), change)
    calls = [json.loads(l) for l in read(lane, ".sdlc", "stub-calls.jsonl").splitlines()]
    new = next((c for c in calls if "new" in c), [])
    check("sdlc's state.py new gets the criteria as --criteria",
          "--criteria" in new and new[new.index("--criteria") + 1:new.index("--criteria") + 4]
          == ["F-ISS-01.AC1", "F-ISS-01.AC2", "F-ISS-01.AC3"], new)
    m = json.loads(read(lane, "acceptance", "manifest.json"))
    check("the lane's manifest lists only its open tests", sorted(t["criterion"] for t in m["tests"])
          == ["F-ISS-01.AC1", "F-ISS-01.AC2"], m)
    check("…copied byte-identical, with the seed they use",
          all(read(lane, "acceptance", "http", f"F-ISS-01.AC{i}.yaml") == read(wb, "docs", "acceptance", "http", f"F-ISS-01.AC{i}.yaml")
              for i in (1, 2)) and os.path.exists(os.path.join(lane, "acceptance", "seed", "base.yaml")))
    lock = json.loads(read(lane, ".rebuild", "criteria.lock.json"))
    hidden_row = next(c for c in lock["criteria"] if c["id"] == "F-ISS-01.AC3")
    check("the lock copy points spec into the workbench submodule, and names no hidden test",
          lock["spec"] == "workbench/docs" and hidden_row["test"] is None, lock["spec"])
    check("sdlc's config names the lock copy as spec_lock",
          json.loads(read(lane, ".sdlc", "config.json")).get("spec_lock") == ".rebuild/criteria.lock.json")
    good = read(wb, "docs", "acceptance", "http", "F-ISS-01.AC2.yaml")
    w(wb, "docs/acceptance/http/F-ISS-01.AC2.yaml", good + "# edited\n")
    r = lane_plan("refresh", "S1", "api")
    check("a test whose sha256 differs from the workbench manifest is refused, not copied",
          r.returncode == 1 and "sha256" in r.stderr and read(lane, "acceptance", "http", "F-ISS-01.AC2.yaml") == good, r.stderr)
    w(wb, "docs/acceptance/http/F-ISS-01.AC2.yaml", good)
    manifest = read(wb, "docs", "acceptance", "manifest.json")
    w(wb, "docs/acceptance/manifest.json", manifest.replace('"http/F-ISS-01.AC2.yaml"', '"../../../p-holdout/http/F-ISS-01.AC3.yaml"'))
    r = lane_plan("refresh", "S1", "api")
    check("a manifest path that leaves the bundle is refused, nothing copied",
          r.returncode == 1 and "leave" in r.stderr and read(lane, "acceptance", "http", "F-ISS-01.AC2.yaml") == good, r.stderr)
    w(wb, "docs/acceptance/manifest.json", manifest)
    w(wb, "rebuild.yaml", "budgets:\n  parallel_lanes: 1\n")
    commit(wb)
    run(["git", "worktree", "add", "-q", "-b", "slice/S1-web", os.path.join(proj, "app-web")], app)
    r = lane_plan("S1", "web", "--worktree", "../app-web", "--features", "F-ISS-02", "--approved-by", "Eval")
    check("a lane beyond the slice's lane cap (rebuild.yaml budgets.parallel_lanes) is refused",
          r.returncode == 1 and "parallel_lanes" in r.stderr, r.stdout + r.stderr)

    w(app, ".gitmodules", '[submodule "workbench"]\n\tpath = workbench\n\turl = ../p-workbench\n'
                          '[submodule "t"]\n\tpath = t\n\turl = ../p-holdout\n')
    w(wb, "rebuild.yaml", "budgets:\n  parallel_lanes: 3\n")
    r = lane_plan("S1", "web", "--worktree", "../app-web", "--features", "F-ISS-02", "--approved-by", "Eval")
    check("a lane is refused while a listed code repo references the holdout repo",
          r.returncode == 1 and "holdout" in r.stderr, r.stdout + r.stderr)
    w(app, ".gitmodules", '[submodule "workbench"]\n\tpath = workbench\n\turl = ../p-workbench\n')
    w(wb, "rebuild.yaml", "budgets:\n  parallel_lanes: 1\n")

if ONLY in (None, "step0"):
    print("\n# step 0 (AC-017)")
    r = lane_plan("step0", "S1")
    check("slice 1 passes step 0: every criterion has a level 2 test or rspec's reason", r.returncode == 0, r.stdout + r.stderr)
    r = lane_plan("step0", "S2")
    check("slice 2 fails step 0, naming the criterion and the rspec:verify run",
          r.returncode == 1 and "F-PRJ-01.AC1" in r.stdout + r.stderr and "rspec:verify --only F-PRJ-01" in r.stdout + r.stderr,
          r.stdout + r.stderr)
    os.replace(os.path.join(wb, "docs", "criteria.lock.json"), os.path.join(wb, "docs", "criteria.lock.off"))
    r = lane_plan("step0", "S1")
    os.replace(os.path.join(wb, "docs", "criteria.lock.off"), os.path.join(wb, "docs", "criteria.lock.json"))
    check("step 0 before rspec:check says what is missing, no traceback",
          r.returncode == 1 and "criteria.lock.json" in r.stderr and "Traceback" not in r.stderr, r.stderr)
    run(["git", "worktree", "add", "-q", "-b", "slice/S2-pm", os.path.join(proj, "app-pm")], app)
    r = lane_plan("S2", "pm", "--worktree", "../app-pm", "--features", "F-PRJ-01", "--approved-by", "Eval")
    check("…and lane_plan will not open the slice's lanes", r.returncode == 1 and "step 0" in r.stderr, r.stdout + r.stderr)

if ONLY in (None, "questions"):
    print("\n# spec questions (AC-018)")
    w(lane, ".sdlc/.work/spec-questions/feat-SQ-0001.json", json.dumps({
        "id": "SQ-0001", "source": "sdlc-question", "class": "spec-gap", "criterion": "F-ISS-01.AC2",
        "question": "Does a closed issue count toward the key sequence?"}))
    w(lane, ".sdlc/.work/spec-questions/feat-SQ-0002.json", json.dumps({
        "id": "SQ-0002", "criterion": "F-ISS-01.AC1 | x | y | z |\n| F-ISS-09.AC1 | injected row", "question": "q"}))
    r = lane_plan("questions", "S1")
    batch = read(wb, "plan", "spec-questions", "S1.md") if r.returncode == 0 else ""
    check("a lane-written criterion cannot add a row or a line to the batch",
          "\n| F-ISS-09.AC1" not in batch and len([l for l in batch.splitlines() if l.startswith("| ")]) == 3, batch)
    r = lane_plan("questions", "../x")
    check("questions refuses a slice id that is not S<n>", r.returncode == 1, r.stdout + r.stderr)
    check("the slice's questions are batched with criterion, question and lane",
          "F-ISS-01.AC2" in batch and "closed issue count" in batch and "api" in batch, r.stdout + r.stderr + batch)
    LOCK["criteria"][1]["text_sha256"] = "1" * 64
    w(wb, "docs/criteria.lock.json", json.dumps(LOCK, indent=2))
    commit(wb)
    r = lane_plan("refresh", "S1", "api")
    copy = json.loads(read(lane, ".rebuild", "criteria.lock.json"))
    check("refresh re-copies the amended lock into the lane",
          r.returncode == 0 and copy["criteria"][1]["text_sha256"] == "1" * 64 and copy["spec"] == "workbench/docs",
          r.stdout + r.stderr)

if ONLY in (None, "flows"):
    print("\n# the recorded bundle stays read-only (AC-008)")

    def edit(path):
        payload = {"session_id": "lanes-eval", "cwd": wb, "hook_event_name": "PreToolUse", "tool_name": "Write",
                   "tool_input": {"file_path": path, "content": "loosened\n"}}
        return run([sys.executable, os.path.join(HOOKS, "flows_guard.py")], wb, {"CLAUDE_PROJECT_DIR": wb},
                   stdin=json.dumps(payload))

    target = os.path.join(wb, "docs", "acceptance", "http", "F-ISS-01.AC1.yaml")
    r = edit(target)
    check("editing a committed recorded test under docs/acceptance/ is blocked", r.returncode == 2 and "flows.py" in r.stderr,
          r.stdout + r.stderr)
    r = run([sys.executable, os.path.join("scripts", "flows.py"), "unlock", "--acceptance", "--reason", "rspec:amend changed AC1"], wb)
    check("flows.py unlock --acceptance logs the decision", r.returncode == 0 and "rspec:amend changed AC1" in
          read(wb, "docs", "acceptance", "DECISIONS.md"), r.stdout + r.stderr)
    check("…and the guard lets the edit through while it is unlocked", edit(target).returncode == 0)
    r = run([sys.executable, os.path.join("scripts", "pause_check.py")], wb)
    check("…and pause_check flags the unlocked bundle, naming the relock",
          "docs/acceptance: recorded assertions still UNLOCKED" in r.stdout + r.stderr
          and "flows.py relock --acceptance" in r.stdout + r.stderr, r.stdout + r.stderr)
    run([sys.executable, os.path.join("scripts", "flows.py"), "relock", "--acceptance"], wb)
    check("relock puts the guard back", edit(target).returncode == 2)

if ONLY in (None, "archive"):
    print("\n# the slice review reads each lane's record, and only a shipped lane is archived")
    if ONLY == "archive":
        lane_plan("S1", "api", "--worktree", "../app-lane", "--features", "F-ISS-01", "--approved-by", "Eval")
    cdir = os.path.join(lane, "docs", "sdlc", "changes")
    change_p = os.path.join(cdir, sorted(os.listdir(cdir))[0])
    state_p = next(os.path.join(lane, ".sdlc", "state", f) for f in os.listdir(os.path.join(lane, ".sdlc", "state"))
                   if f.endswith(".md"))

    def review():
        run([sys.executable, os.path.join("scripts", "slice_review.py"), "S1"], wb)
        return read(wb, "plan", "slice-reviews", "S1.md")

    sr = review()
    check("the slice review lists the lane's sdlc record", re.search(r"- api: sdlc `.*-s1-api` · Status: active", sr)
          is not None and "no longer matches what lane_plan.py wrote" not in sr, sr[:1500])
    w(lane, os.path.relpath(change_p, lane), read(change_p).replace("→ F-ISS-01.AC1", "→ F-ISS-01.AC9"))
    check("a lane that rewrote its cited criteria is named in the review",
          "no longer matches what lane_plan.py wrote" in review())
    r = lane_plan("archive", "S1", "api")
    check("archive refuses a lane sdlc has not shipped", r.returncode == 1 and "Status: active" in r.stderr, r.stderr)
    w(lane, os.path.relpath(state_p, lane), read(state_p).replace("Status: active", "Status: done"))
    r = lane_plan("archive", "S1", "api")
    check("a shipped lane is archived to the workbench, its edited criteria flagged", r.returncode == 0
          and os.path.isdir(os.path.join(wb, "plan", "lane-plans", "archive", "S1-api"))
          and "acceptance criteria differ" in r.stdout, r.stdout + r.stderr)
    check("a lane is archived once", lane_plan("archive", "S1", "api").returncode == 1)
    recp = os.path.join(wb, "plan", "lane-plans", "S1.yaml")
    rec = json.loads(re.sub(r"^#.*\n", "", read(recp), flags=re.M))
    rec["lanes"]["ghost"] = {"worktree": os.path.join(base, "no-such-worktree")}
    w(wb, "plan/lane-plans/S1.yaml", "# eval\n" + json.dumps(rec))
    r = run([sys.executable, os.path.join("scripts", "boundary.py"), "S1"], wb)
    check("boundary names a lane it cannot archive, and does not pass", r.returncode == 2 and "ghost: NOT archived" in r.stdout,
          r.stdout[:800])

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
