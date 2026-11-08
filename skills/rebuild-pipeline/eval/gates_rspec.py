#!/usr/bin/env python3
"""gates_rspec.py (eval) — 3.0.0, spec 05 P2: do the gates lock rspec's artifacts, in rspec's order,
and does `gate.py status` read rspec's own progress instead of guessing it?

  python3 skills/rebuild-pipeline/eval/gates_rspec.py [order|level2|progress]

WHY IT EXISTS. In 3.0 rspec writes the spec and the tests, and the gates are the only record that a
person approved them. A gate that locks the wrong files, or locks before rspec's own check of the
stage it closes, pins an artifact nobody reviewed; Gate 4's level 2 floor is the one number that says
the tests were recorded against the reference rather than written from the spec. This scaffolds a
workbench with rebuild_init.py, writes the rspec files by hand (no model call), and drives gate.py.
With an argument it runs one group, which is how the change file's acceptance tests name them.
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
ONLY = sys.argv[1] if len(sys.argv) > 1 else None

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'' if ok or not detail else chr(10) + '      ' + str(detail)}")
    if not ok:
        failures += 1


base = tempfile.mkdtemp(prefix="gates-rspec-eval-")
ENV = {"GIT_AUTHOR_NAME": "Eval", "GIT_AUTHOR_EMAIL": "eval@x", "GIT_COMMITTER_NAME": "Eval",
       "GIT_COMMITTER_EMAIL": "eval@x", "RSPEC_PLUGIN_ROOT": os.path.join(base, "no-rspec-here")}


def run(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, **ENV, **(env or {})})


def w(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def workbench(name):
    d = os.path.join(base, name)
    os.makedirs(d)
    r = run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "p", "--dir", d], d)
    check(f"{name}: rebuild_init creates the workbench", r.returncode == 0, r.stderr)
    return os.path.join(d, "p-workbench")


def commit(wb):
    run(["git", "add", "-A"], wb)
    run(["git", "commit", "-qm", "eval"], wb)


def gate(wb, *args, env=None):
    return run([sys.executable, os.path.join("scripts", "gate.py"), *args], wb, env)


def rspec_json(wb, stage, kind="http"):
    w(wb, "docs/rspec.json", json.dumps({"product": "p", "goal": "production", "stage": stage, "reference": {"run": {"kind": kind}}}))


def lock_text(wb, gid):
    with open(os.path.join(wb, "locks", f"{gid}.yaml"), encoding="utf-8") as f:
        return f.read()


def criteria(levels):
    """A criteria.lock.json (contracts C3) with one MVP criterion per level given, plus a Later one at 0."""
    rows = [{"id": f"F-ISS-01.AC{i + 1}", "feature": "F-ISS-01", "file": "docs/stories/F-ISS-01.md",
             "text_sha256": "0" * 64, "tag": "observed", "priority": "MVP", "level": lv,
             "test": f"acceptance/http/F-ISS-01.AC{i + 1}.yaml" if lv == 2 else None, "departures": []}
            for i, lv in enumerate(levels)]
    rows.append({"id": "F-ISS-02.AC1", "feature": "F-ISS-02", "file": "docs/stories/F-ISS-02.md", "text_sha256": "0" * 64,
                 "tag": "docs", "priority": "Later", "level": 0, "test": None, "departures": []})
    return json.dumps({"contracts": "1.1.1", "spec": "docs", "generated": "2026-11-08T00:00:00Z", "criteria": rows})


def through_gate2(wb):
    """Everything rspec writes up to handoff, with gates 1, 3 and 2 locked."""
    rspec_json(wb, "handoff")
    for rel in ("docs/features.md", "docs/domain.md", "docs/departures.yaml",
                "docs/audit/summary.md", "docs/verify/summary.md"):
        w(wb, rel, f"# {rel}\n")
    w(wb, "docs/build-plan.md", "# Build plan\n\n## Slice 1: issues\n\n| 1 | F-ISS-01 a | | | | | |\n")
    w(wb, "docs/decisions/0001-stack.md", "# Stack\n\n- Status: Accepted\n")
    commit(wb)
    for gid in ("gate-1", "gate-3", "gate-2"):
        r = gate(wb, "lock", gid, "--by", "Eval")
        check(f"{gid} locks once rspec's files for it exist", r.returncode == 0, r.stdout + r.stderr)


def contracts(wb, levels, posture):
    w(wb, "docs/openapi.json", "{}\n")
    w(wb, "docs/schemas/issue.json", "{}\n")
    if not os.path.exists(os.path.join(wb, "docs", "acceptance", "manifest.json")):
        w(wb, "docs/acceptance/manifest.json", '{"contracts": "1.1.1", "tests": []}\n')
    w(wb, "docs/criteria.lock.json", criteria(levels))
    src = os.path.join(wb, "sources.yaml")
    text = open(src, encoding="utf-8").read()
    with open(src, "w", encoding="utf-8", newline="\n") as f:
        f.write(re.sub(r"^(  posture:).*$", rf'\1 "{posture}"', text, count=1, flags=re.M))
    if not os.path.exists(os.path.join(wb, "plan", "holdout.json")):
        # Gate 4 records the hidden-test draw (B3), so it is made once, before the first lock.
        r = run([sys.executable, os.path.join("scripts", "holdout.py"), "split", "--seed", "1"], wb)
        check("the holdout split runs before gate-4", r.returncode == 0, r.stdout + r.stderr)
    commit(wb)


if ONLY in (None, "order"):
    print("\n# order and rspec artifacts (AC-006)")
    wb = workbench("order")
    r = gate(wb, "status")
    ids = re.findall(r"^(gate-[0-9])", r.stdout, re.M)
    check("status lists the gates in rspec's order: 1, 3, 2, 4, 5", ids == ["gate-1", "gate-3", "gate-2", "gate-4", "gate-5"],
          r.stdout)
    rspec_json(wb, "discovered")
    for rel in ("docs/features.md", "docs/domain.md", "docs/departures.yaml"):
        w(wb, rel, f"# {rel}\n")
    commit(wb)
    r = gate(wb, "lock", "gate-1")
    check("gate-1 refuses before rspec's features are approved", r.returncode == 1 and "features-approved" in r.stderr,
          r.stdout + r.stderr)
    rspec_json(wb, "features-approved")
    commit(wb)
    r = gate(wb, "lock", "gate-1", "--by", "Eval")
    lock1 = lock_text(wb, "gate-1")
    check("gate-1 locks features.md, domain.md and departures.yaml",
          r.returncode == 0 and all(f"  docs/{f}: " in lock1 for f in ("features.md", "domain.md", "departures.yaml")),
          r.stdout + r.stderr + lock1)
    r = gate(wb, "lock", "gate-2")
    check("gate-2 refuses while gate-3 (now before it) is open", r.returncode == 1 and "gate-3" in r.stderr, r.stderr)
    w(wb, "docs/decisions/0001-stack.md", "# Stack\n\n- Status: Proposed\n")
    commit(wb)
    r = gate(wb, "lock", "gate-3")
    check("gate-3 refuses while an ADR is still Proposed", r.returncode == 1 and "0001-stack.md" in r.stderr, r.stderr)
    w(wb, "docs/decisions/0001-stack.md", "# Stack\n\n- Status: Accepted\n")
    commit(wb)
    r = gate(wb, "lock", "gate-3", "--by", "Eval")
    check("gate-3 locks docs/decisions/ once every ADR is decided",
          r.returncode == 0 and "  docs/decisions/0001-stack.md: " in lock_text(wb, "gate-3"), r.stdout + r.stderr)
    w(wb, "docs/build-plan.md", "# Build plan\n")
    commit(wb)
    r = gate(wb, "lock", "gate-2")
    check("gate-2 refuses before rspec's audit and verify have finished", r.returncode == 1 and "audit" in r.stderr, r.stderr)
    w(wb, "docs/audit/summary.md", "# Audit\n")
    rspec_json(wb, "handoff", kind="none")
    commit(wb)
    r = gate(wb, "lock", "gate-2", "--by", "Eval")
    check("gate-2 locks build-plan.md once the audit is done (verify skipped: reference.run.kind none)",
          r.returncode == 0 and "  docs/build-plan.md: " in lock_text(wb, "gate-2"), r.stdout + r.stderr)

if ONLY in (None, "level2"):
    print("\n# Gate 4's level 2 floor (AC-012)")
    wb = workbench("level2")
    through_gate2(wb)
    contracts(wb, [2, 2, 2, 2, 2, 2, 2, 2, 1, 1], "observe")
    r = gate(wb, "lock", "gate-4")
    check("observe: MVP level 2 at 80% refuses gate-4 and says how to sign a reason",
          r.returncode == 1 and "80%" in r.stderr and "--accept-level2" in r.stderr, r.stdout + r.stderr)
    r = gate(wb, "lock", "gate-4", "--accept-level2", "seeding needs a paid account", "--by", "Tam Mai")
    lock4 = lock_text(wb, "gate-4")
    check("…a signed reason locks it and the lock records share, reason and who",
          r.returncode == 0 and "level2_waiver:" in lock4 and "seeding needs a paid account" in lock4
          and "Tam Mai" in lock4 and "0.8" in lock4, r.stdout + r.stderr + lock4)
    check("gate-4 locks openapi.json, schemas/, criteria.lock.json and acceptance/manifest.json",
          all(f"  docs/{f}: " in lock4 for f in ("openapi.json", "schemas/issue.json", "criteria.lock.json",
                                                 "acceptance/manifest.json")), lock4)
    gate(wb, "reopen", "gate-4", "--reason", "eval")
    contracts(wb, [2, 2, 2, 2, 2, 2, 2, 2, 1, 1], "strict")
    r = gate(wb, "lock", "gate-4", "--by", "Eval")
    check("strict: the same share is reported, not refused", r.returncode == 0 and "80%" in r.stdout + r.stderr,
          r.stdout + r.stderr)
    gate(wb, "reopen", "gate-4", "--reason", "eval")
    contracts(wb, [2] * 9 + [1], "own-code")
    r = gate(wb, "lock", "gate-4", "--by", "Eval")
    check("own-code: 90% locks with no reason asked", r.returncode == 0 and "level2_waiver" not in lock_text(wb, "gate-4"),
          r.stdout + r.stderr)

if ONLY in (None, "progress"):
    print("\n# rspec's progress (AC-013)")
    wb = workbench("progress")
    r = gate(wb, "status")
    check("status says rspec's progress was not run, and why, when rspec cannot be found",
          re.search(r"^rspec: not run: .+", r.stdout, re.M) is not None, r.stdout)
    fake = os.path.join(base, "rspec-plugin")
    w(fake, "scripts/progress.py", "import json, sys\nprint(json.dumps({'stage': 'stories', 'next': 'tech', "
                                   "'pending': ['api', 'nfr'], 'arg': sys.argv[1]}))\n")
    r = gate(wb, "status", env={"RSPEC_PLUGIN_ROOT": fake})
    check("status prints rspec's own stage, next step and pending units from its progress.py",
          re.search(r"^rspec: stage stories, next tech, pending api, nfr$", r.stdout, re.M) is not None, r.stdout)

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
