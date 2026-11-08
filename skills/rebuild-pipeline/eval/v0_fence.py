#!/usr/bin/env python3
"""v0_fence.py (eval) — E23, 2.0.0 and 3.0.0: does this release refuse to touch a workbench an
older release made?

  python3 skills/rebuild-pipeline/eval/v0_fence.py

WHY IT EXISTS. 3.0.0 is a breaking release with no migration (spec 05, D7): a 2.x lane is an sdlc
feature fed by this plugin's own mining, a 1.x lane worked under a PLAN.md, and 0.x was a different
plugin altogether. What nothing stops is someone pointing 3.x at a rebuild still in flight. The
workbench marker, `locks/pipeline.yaml` carrying `rebuild_major: 3`, is what tells them apart, and
every place 3.x acts on a workbench has to honour it: the guards (which fire in every session the
plugin is enabled in), `upgrade.py --auto` (which runs at every session start and would copy 3.x's
scripts over the older ones), and scaffold-repo. This builds a 3.x workbench and 2.x-, 1.x- and
0.x-shaped ones, asserts the older ones are left alone, and that a 2.x one is told to finish on
2.2.0, the last 2.x release. (The file keeps its 1.0.0 name.)

An older-shaped workbench is the 3.x one marked with the older number; a 0.x-shaped one has the
marker line deleted, which is exactly what its absence means.
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SCRIPTS = os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts")
HOOKS = os.path.join(ROOT, "hooks", "scripts")

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


def run(cmd, cwd=None, stdin=None, env=None):
    return subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, **(env or {})})


def tree_hash(root: str) -> str:
    h = hashlib.sha256()
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "__pycache__"))
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            h.update(os.path.relpath(p, root).encode())
            h.update(open(p, "rb").read())
    return h.hexdigest()


base = tempfile.mkdtemp(prefix="v0-fence-eval-")
proj = os.path.join(base, "proj")
os.makedirs(proj)
init = run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "p", "--dir", proj])
check("rebuild_init creates the workbench", init.returncode == 0, init.stderr)
wb3 = os.path.join(proj, "p-workbench")
pipeline = open(os.path.join(wb3, "locks", "pipeline.yaml")).read()
check("a new workbench is marked rebuild_major: 3", re.search(r"^rebuild_major: 3$", pipeline, re.M) is not None, pipeline)


def marked(major: int, where: str) -> str:
    """The 3.x workbench marked `major`: what an older workbench is, as far as 3.x can tell."""
    wb = os.path.join(base, where, "p-workbench")
    shutil.copytree(wb3, wb)
    p = os.path.join(wb, "locks", "pipeline.yaml")
    open(p, "w").write(pipeline.replace("rebuild_major: 3\n", f"rebuild_major: {major}\n"))
    check(f"the {major}.x-shaped copy says rebuild_major: {major}",
          re.search(rf"^rebuild_major: {major}$", open(p).read(), re.M) is not None)
    return wb


wb2 = marked(2, "two")
wb1 = marked(1, "one")

# The same workbench with the marker removed: what a 0.x workbench is.
wb0 = os.path.join(base, "old", "p-workbench")
shutil.copytree(wb3, wb0)
p0 = os.path.join(wb0, "locks", "pipeline.yaml")
open(p0, "w").write(re.sub(r"^# Which major release.*?^rebuild_major: 3\n", "", pipeline, flags=re.M | re.S))
check("the 0.x-shaped copy has no marker", "rebuild_major" not in open(p0).read())

# --- guards -------------------------------------------------------------------------------------
print("\n# guards")


def project_with(wb_src: str, name: str) -> tuple[str, str]:
    """A project dir holding a workbench copy, a listed repo with a git history, and a locked gate."""
    d = os.path.join(base, name)
    wb = os.path.join(d, "p-workbench")
    shutil.copytree(wb_src, wb)
    repo = os.path.join(d, "app")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    open(os.path.join(repo, "README.md"), "w").write("x\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=E", "-c", "user.email=e@x", "commit", "-qm", "init"], cwd=repo, check=True)
    open(os.path.join(wb, "repos.yaml"), "w").write("repos:\n  - name: app\n    path: ../app\n")
    open(os.path.join(wb, "locks", "gate-1.yaml"), "w").write("gate: gate-1\nstatus: locked\nprotects:\n  - matrix\n")
    os.makedirs(os.path.join(wb, "matrix"), exist_ok=True)
    open(os.path.join(wb, "matrix", "features.yaml"), "w").write("[]\n")
    return d, wb


def guard(script: str, payload: dict, root: str):
    return run([sys.executable, os.path.join(HOOKS, script)], stdin=json.dumps({"session_id": "v0-fence", "cwd": root, **payload}),
               env={"CLAUDE_PROJECT_DIR": root})


big = "\n".join(f"line {i}" for i in range(40)) + "\n"
for label, src in (("3.x", wb3), ("2.x-shaped", wb2), ("1.x-shaped", wb1), ("0.x-shaped", wb0)):
    d, wb = project_with(src, f"proj-{label[0]}")
    blocks_expected = label == "3.x"
    write = guard("spec_gate_guard.py", {"hook_event_name": "PreToolUse", "tool_name": "Write",
                                         "tool_input": {"file_path": os.path.join(d, "app", "a.go"), "content": big}}, d)
    check(f"spec gate on a {label} workbench's repo: {'blocks with no plan' if blocks_expected else 'does nothing'}",
          (write.returncode == 2) == blocks_expected, write.stderr)
    push = guard("bash_guard.py", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                   "tool_input": {"command": "cd app && git push --force"}}, d)
    check(f"bash guard on a {label} workbench's repo: {'blocks a force push' if blocks_expected else 'does nothing'}",
          (push.returncode == 2) == blocks_expected, push.stderr)
    locked = guard("gate_guard.py", {"hook_event_name": "PreToolUse", "tool_name": "Write",
                                     "tool_input": {"file_path": os.path.join(wb, "matrix", "features.yaml"), "content": "x"}}, d)
    check(f"gate guard on a {label} workbench's locked file: {'blocks' if blocks_expected else 'does nothing'}",
          (locked.returncode == 2) == blocks_expected, locked.stderr)
    tmp = tempfile.gettempdir()
    canary = os.path.join(tmp, "rebuild-canary-v0-fence")
    if os.path.exists(canary):
        os.remove(canary)
    guard("canary_seed.py", {"hook_event_name": "SessionStart"}, d)
    seeded = os.path.exists(canary)
    check(f"canary seed in a {label} session: {'seeds' if blocks_expected else 'does not seed'}", seeded == blocks_expected)
    if seeded:
        os.remove(canary)

# --- upgrade.py ---------------------------------------------------------------------------------
print("\n# upgrade")
open(os.path.join(wb0, ".rebuild-plugin"), "w").write(ROOT + "\n")
before = tree_hash(wb0)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--plugin", ROOT], cwd=wb0)
check("upgrade.py refuses a 0.x workbench and says to finish it where it was made", r.returncode == 1 and "0.x" in r.stderr and "will not touch it" in r.stderr, r.stderr + r.stdout)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--auto", "--plugin", ROOT], cwd=wb0)
check("--auto, the session-start path, prints one TOOLING line and exits 0 (a session start must not fail on someone else's workbench)",
      r.returncode == 0 and r.stdout.startswith("TOOLING  skipped:") and len(r.stdout.strip().splitlines()) == 1, r.stdout + r.stderr)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--apply", "--plugin", ROOT], cwd=wb0)
check("--apply is refused the same way", r.returncode == 1)
check("…and nothing in the 0.x workbench changed", tree_hash(wb0) == before)
open(os.path.join(wb1, ".rebuild-plugin"), "w").write(ROOT + "\n")
before1 = tree_hash(wb1)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--apply", "--plugin", ROOT], cwd=wb1)
check("upgrade.py refuses a 1.x workbench too, naming 1.x", r.returncode == 1 and "1.x release" in r.stderr and "will not touch it" in r.stderr, r.stderr + r.stdout)
check("…and nothing in the 1.x workbench changed", tree_hash(wb1) == before1)
open(os.path.join(wb2, ".rebuild-plugin"), "w").write(ROOT + "\n")
before2 = tree_hash(wb2)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--apply", "--plugin", ROOT], cwd=wb2)
check("upgrade.py refuses a 2.x workbench and names 2.2.0, the last 2.x release",
      r.returncode == 1 and "2.x release" in r.stderr and "2.2.0" in r.stderr and "will not touch it" in r.stderr, r.stderr + r.stdout)
check("…and nothing in the 2.x workbench changed", tree_hash(wb2) == before2)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--auto", "--plugin", ROOT], cwd=wb2)
check("--auto on a 2.x workbench prints one TOOLING line naming 2.2.0 and exits 0",
      r.returncode == 0 and r.stdout.startswith("TOOLING  skipped:") and "2.2.0" in r.stdout
      and len(r.stdout.strip().splitlines()) == 1, r.stdout + r.stderr)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--plugin", ROOT], cwd=wb3)
check("on a 3.x workbench upgrade.py runs normally", r.returncode == 0 and "will not touch it" not in r.stderr, r.stderr + r.stdout)

# --- scaffold -----------------------------------------------------------------------------------
print("\n# scaffold-repo")
repo = os.path.join(base, "newrepo")
os.makedirs(repo)
scaffold = os.path.join(ROOT, "skills", "scaffold-repo", "scripts", "scaffold.py")
for label, src in (("0.x", wb0), ("1.x", wb1), ("2.x", wb2)):
    r = run([sys.executable, scaffold, "plan", "--workbench", src], cwd=repo)
    check(f"scaffold.py will not scaffold for a {label} workbench", r.returncode == 1 and "not made by a 3.x release" in r.stderr, r.stderr)

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
