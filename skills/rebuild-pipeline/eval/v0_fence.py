#!/usr/bin/env python3
"""v0_fence.py (eval) — E23: does 1.x refuse to touch a workbench a 0.x release made?

  python3 skills/rebuild-pipeline/eval/v0_fence.py

WHY IT EXISTS. 1.x ships as a different plugin, so an install of 0.x can never be updated into it.
What that does not stop is the two being enabled side by side, or someone pointing 1.x at a rebuild
that is still in flight. The workbench marker, `locks/pipeline.yaml` carrying `rebuild_major: 1`, is
what tells them apart, and every place 1.x acts on a workbench has to honour it: the guards (which
fire in every session the plugin is enabled in), `upgrade.py --auto` (which runs at every session
start and would copy 1.x's scripts over 0.x's), and scaffold-repo. This builds a 1.x workbench and a
0.x-shaped one and asserts each of those treats them differently.

A 0.x-shaped workbench is the 1.x one with the marker line deleted: that is exactly what the marker's
absence means.
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
wb1 = os.path.join(proj, "p-workbench")
pipeline = open(os.path.join(wb1, "locks", "pipeline.yaml")).read()
check("a new workbench is marked rebuild_major: 1", re.search(r"^rebuild_major: 1$", pipeline, re.M) is not None, pipeline)

# The same workbench with the marker removed: what a 0.x workbench is, as far as 1.x can tell.
wb0 = os.path.join(base, "old", "p-workbench")
shutil.copytree(wb1, wb0)
p0 = os.path.join(wb0, "locks", "pipeline.yaml")
open(p0, "w").write(re.sub(r"^# Which major release.*?^rebuild_major: 1\n", "", pipeline, flags=re.M | re.S))
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
for label, src in (("1.x", wb1), ("0.x-shaped", wb0)):
    d, wb = project_with(src, f"proj-{label[0]}")
    blocks_expected = label == "1.x"
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
check("upgrade.py refuses a 0.x workbench and says to finish it on 0.x", r.returncode == 1 and "0.x" in r.stderr and "will not touch it" in r.stderr, r.stderr + r.stdout)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--auto", "--plugin", ROOT], cwd=wb0)
check("--auto, the session-start path, prints one TOOLING line and exits 0 (a session start must not fail on someone else's workbench)",
      r.returncode == 0 and r.stdout.startswith("TOOLING  skipped:") and len(r.stdout.strip().splitlines()) == 1, r.stdout + r.stderr)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--apply", "--plugin", ROOT], cwd=wb0)
check("--apply is refused the same way", r.returncode == 1)
check("…and nothing in the 0.x workbench changed", tree_hash(wb0) == before)
r = run([sys.executable, os.path.join(SCRIPTS, "upgrade.py"), "--plugin", ROOT], cwd=wb1)
check("on a 1.x workbench upgrade.py runs normally", r.returncode == 0 and "will not touch it" not in r.stderr, r.stderr + r.stdout)

# --- scaffold -----------------------------------------------------------------------------------
print("\n# scaffold-repo")
repo = os.path.join(base, "newrepo")
os.makedirs(repo)
scaffold = os.path.join(ROOT, "skills", "scaffold-repo", "scripts", "scaffold.py")
r = run([sys.executable, scaffold, "plan", "--workbench", wb0], cwd=repo)
check("scaffold.py will not scaffold for a 0.x workbench", r.returncode == 1 and "not made by a 1.x release" in r.stderr, r.stderr)

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
