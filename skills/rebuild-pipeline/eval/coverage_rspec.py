#!/usr/bin/env python3
"""coverage_rspec.py (eval) — 3.0.0, spec 05 P6 step 4: do the coverage and regression reports, the slice order and
`gate.py status` read rspec's build plan and feature list, and does a boundary say `not run` when they cannot run?

  python3 skills/rebuild-pipeline/eval/coverage_rspec.py [reports|order|notrun]

WHY IT EXISTS. 2.x read its slices and features from `plan/slices.yaml` and `matrix/features.yaml`, which a 3.x
workbench never has; the reports then printed "nothing to read" as step 4's output and the boundary went on as if
step 4 had run. Each group builds a throwaway workbench with rebuild_init.py and rspec's files. No model call. With
an argument it runs one group, which is how the change file's acceptance tests name them.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
SCRIPTS = os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts")
ONLY = sys.argv[1] if len(sys.argv) > 1 else None

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'' if ok or not detail else chr(10) + '      ' + str(detail)}")
    if not ok:
        failures += 1


base = tempfile.mkdtemp(prefix="coverage-rspec-eval-")
ENV = {"GIT_AUTHOR_NAME": "Eval", "GIT_AUTHOR_EMAIL": "eval@x", "GIT_COMMITTER_NAME": "Eval",
       "GIT_COMMITTER_EMAIL": "eval@x", "RSPEC_PLUGIN_ROOT": os.path.join(base, "no-rspec")}


def w(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(root, rel):
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8") as f:
        return f.read()


def script(wb, name, *a):
    return subprocess.run([sys.executable, os.path.join("scripts", name), *a], cwd=wb, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ, **ENV})


def workbench(name, spec=True):
    d = os.path.join(base, name)
    os.makedirs(d)
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "p", "--dir", d],
                   capture_output=True, check=True, env={**os.environ, **ENV})
    wb = os.path.join(d, "p-workbench")
    if not spec:
        return wb
    w(wb, "docs/features.md",
      "# Features\n\n## Feature list\n\n"
      "| ID | Module | Feature | Behaviour (one line) | Priority | Reason | Research ID |\n"
      "|---|---|---|---|---|---|---|\n"
      "| F-AB-01 | AB | Alpha | a | MVP | J1 | R-1 |\n"
      "| F-AB-02 | AB | Beta | b | MVP | J2 | R-2 |\n"
      "| F-AB-03 | AB | Gamma | c | Drop | not used → D-001 | R-3 |\n"
      "| F-CD-01 | CD | Delta | d | MVP | J3 | R-4 |\n"
      "| F-EF-01 | EF | Epsilon | e | Later | after MVP | R-5 |\n")
    w(wb, "docs/build-plan.md",
      "# Build plan\n\n## Release 1: MVP\nusers can work\n\n"
      "## Slice 1: one\nGoal: alpha works\n\n| Order | Feature | Story | Criteria |\n|---|---|---|---|\n"
      "| 1 | F-AB-01 Alpha | features/F-AB-01-alpha.md | F-AB-01.AC1 |\n\nDone when: alpha passes its tests.\n\n"
      "## Slice 2: two\n\n| 1 | F-AB-02 Beta | features/F-AB-02-beta.md | F-AB-02.AC1 |\n\n"
      "## Slice 3: three\n\n| 1 | F-CD-01 Delta | features/F-CD-01-delta.md | F-CD-01.AC1 |\n\n"
      "## Release 2\n\n## Slice 4: four\n\n| 1 | F-EF-01 Epsilon | features/F-EF-01-epsilon.md | F-EF-01.AC1 |\n")
    for fid, deps in (("F-AB-01-alpha", "[]"), ("F-AB-02-beta", "[F-AB-01]"), ("F-CD-01-delta", "[F-AB-02]"),
                      ("F-EF-01-epsilon", "[]")):
        w(wb, f"docs/features/{fid}.md", f"---\nid: {fid[:7]}\nmodule: {fid[2:4]}\npriority: MVP\ndepends_on: {deps}\n"
                                         f"status: todo\n---\n# {fid}\n")
    w(wb, "plan/progress.yaml", "slices:\n  S1: done\nfeatures:\n  F-AB-01: covered\n")
    return wb


def set_locked(wb, *gates):
    for g in gates:
        p = os.path.join(wb, "locks", f"{g}.yaml")
        w(wb, os.path.join("locks", f"{g}.yaml"), re.sub(r"^status: .*$", "status: locked", read(wb, p), count=1, flags=re.M))


_d = datetime.now()
DATE = f"{_d.year}-{_d.month:02d}-{_d.day:02d}"

if ONLY in (None, "reports"):
    print("\n# coverage, the slice review and gate status read rspec's build plan and features (AC-028)")
    wb = workbench("reports")
    r = script(wb, "parity.py")
    rep = read(wb, f"parity/{DATE}.md")
    check("parity counts features.md's features, a Drop as descoped", r.returncode == 0
          and "Coverage: 1/4 covered (25%)" in rep and "1 descoped" in rep, r.stdout + r.stderr + rep[:600])
    check("…lists the Drop under Descoped and build-plan.md's slices under Slice progress",
          "- F-AB-03 Gamma" in rep.split("## Descoped")[-1] and "- S1 one: done" in rep and "- S4 four: pending" in rep,
          rep[-700:])
    check("under posture observe (the third-party default) equivalence is not reported as not applying",
          "Does not apply" not in rep, rep[:900])
    w(wb, "sources.yaml", "reference:\n  kind: third-party\n  posture: strict\n")
    script(wb, "parity.py")
    rep = read(wb, f"parity/{DATE}.md")
    check("under posture strict it says equivalence does not apply, and why", "Does not apply: `reference.posture` is `strict`"
          in rep, rep[:900])
    r = script(wb, "slice_review.py", "S1")
    rev = read(wb, "plan/slice-reviews/S1.md")
    check("slice_review reviews a build-plan slice, its features and its Done when", r.returncode == 0
          and "F-AB-01 Alpha — **covered**" in rev and "> done_means: alpha passes its tests." in rev
          and "position 1 of 4" in rev, r.stdout + r.stderr + rev[:900])
    set_locked(wb, "gate-1", "gate-3", "gate-2", "gate-4")
    r = script(wb, "gate.py", "status")
    check("gate.py status names the next unfinished build-plan slice",
          "Current phase: G5 build — next unfinished slice S2 (pending), 1/4 slices done" in r.stdout, r.stdout + r.stderr)

if ONLY in (None, "order"):
    print("\n# the slice order keeps the stories' dependencies (AC-029)")
    wb = workbench("order")
    r = script(wb, "sequence.py", "init")
    check("sequence.py init baselines build-plan.md's slices", r.returncode == 0 and "S1 → S2 → S3 → S4" in r.stdout,
          r.stdout + r.stderr)
    r = script(wb, "sequence.py", "reorder", "S3", "--before", "S2", "--reason", "try")
    check("a move before a slice it depends on is refused, naming it", r.returncode == 1
          and "puts S3 before S2, which it depends on" in r.stderr, r.stdout + r.stderr)
    r = script(wb, "sequence.py", "reorder", "S4", "--before", "S2", "--reason", "epsilon first")
    check("a move that keeps every dependency is logged", r.returncode == 0
          and "moved S4 before S2" in read(wb, "plan/sequence-decisions.md"), r.stdout + r.stderr)

if ONLY in (None, "notrun"):
    print("\n# without rspec's files, step 4 says not run (AC-030)")
    wb = workbench("notrun", spec=False)
    r = script(wb, "parity.py")
    check("parity.py exits 1 naming docs/features.md", r.returncode == 1 and "docs/features.md" in r.stderr,
          r.stdout + r.stderr)
    r = script(wb, "slice_review.py", "S1")
    check("slice_review.py exits 1 naming docs/build-plan.md", r.returncode == 1 and "docs/build-plan.md" in r.stderr,
          r.stdout + r.stderr)
    w(wb, "docs/features.md", "# Features\n")
    r = script(wb, "parity.py")
    check("parity.py with features.md but no build-plan.md exits 1 naming docs/build-plan.md",
          r.returncode == 1 and "docs/build-plan.md" in r.stderr, r.stdout + r.stderr)
    os.remove(os.path.join(wb, "docs", "features.md"))
    w(wb, "docs/build-plan.md", "# Build plan\n\n## Slice 1: issues\n\n| 1 | F-ISS-01 a |\n")
    r = script(wb, "slice_review.py", "S1")
    check("slice_review.py with build-plan.md but no features.md exits 1 naming docs/features.md",
          r.returncode == 1 and "docs/features.md" in r.stderr, r.stdout + r.stderr)
    os.remove(os.path.join(wb, "docs", "build-plan.md"))
    r = script(wb, "boundary.py", "S1")
    step4 = r.stdout.split("== 4. coverage: parity")[-1].split("== 5.")[0]
    check("boundary.py prints step 4 as not run, with the reason", "not run: " in step4 and "docs/features.md" in step4
          and "not run: " in step4.split("== 4. regression")[-1], r.stdout[-1500:])

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
