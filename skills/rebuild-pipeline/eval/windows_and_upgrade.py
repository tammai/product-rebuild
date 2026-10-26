#!/usr/bin/env python3
"""windows_and_upgrade.py (eval) — 0.32.0, issue #2: gaps found upgrading a Windows workbench
from plugin 0.22.0 to 0.31.0.

  python3 skills/rebuild-pipeline/eval/windows_and_upgrade.py

Scaffolds a throwaway workbench with rebuild_init.py and runs the REAL scripts against it:
  - CRLF files, as git writes them with core.autocrlf=true: gate.py status counts done slices,
    and gate_guard.py still blocks an edit under a locked gate;
  - a numbered `## 5. Acceptance criteria` heading is read by validate.py;
  - `descoped` + `feature_notes` validate, leave the coverage denominator, and are listed by
    parity.py; a descoped feature with no note fails validate;
  - upgrade.py: a vendored copy re-checked-out as CRLF is current, not modified; a forced
    partial upgrade that breaks an import (both Python import shapes) is named; an --apply that
    makes validate fail warns.
The Windows path-separator fixes (the `--force scripts/x.py` spelling, the lock file's own path in
the dirty-tree check) cannot be reproduced on a POSIX host and are not covered here.

A plain script, not a test framework: it must run on a machine with nothing but Python, which is
the one thing a workbench is guaranteed to have.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
base = tempfile.mkdtemp(prefix="rebuild-eval-")
subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "evalwb", "--dir", base],
               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
wb = os.path.join(base, "evalwb-workbench")


def crlf(t):
    return t.replace("\n", "\r\n")


def w(rel, text):
    p = os.path.join(wb, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    # newline="": the CRLF cases write their own line endings and must reach disk untouched.
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def read(rel):
    p = os.path.join(wb, rel)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8", newline="") as fh:
        return fh.read()


def run(script, *args):
    # PYTHONDONTWRITEBYTECODE: a __pycache__ written into the workbench is an untracked file,
    # which would make every later `git status` in this eval read dirty.
    r = subprocess.run([sys.executable, os.path.join("scripts", script), *args], cwd=wb,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return {"out": r.stdout + r.stderr, "code": r.returncode}


def git(*a):
    return subprocess.run(["git", *a], cwd=wb, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def commit(msg):
    git("add", "-A")
    git("commit", "-qm", msg)


date = time.strftime("%Y-%m-%d")

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + detail.replace("\n", "\n      "))


def slice_(sid, status=None):
    tail = f"  status: {status}\n" if status else ""
    return (f"- id: {sid}\n  name: Slice {sid}\n  features: [F-A-00{sid[1:]}]\n"
            f"  depends_on: []\n  learning_goals: [x]\n  done_means: the slice is usable end to end\n" + tail)


def feature(n):
    return f"- id: F-A-00{n}\n  name: Feature {n}\n  domain: a\n  confidence: high\n  status: planned\n"


w("matrix/features.yaml", "".join(feature(n) for n in (1, 2, 3)))
w("plan/slices.yaml", "".join(slice_(s) for s in ("S1", "S2", "S3")))

# --- 1. CRLF: gate.py status reads the lock files and the progress overlay ------------------
# Gates 1-4 locked, so status has to count slices — the path that read "0/18 slices done".
for g in (1, 2, 3, 4):
    w(f"locks/gate-{g}.yaml", crlf(re.sub(r"^status: .*$", "status: locked", read(f"locks/gate-{g}.yaml"), count=1, flags=re.M)))
w("plan/progress.yaml", crlf("slices:\n  S1: done\n\n  S2: done\nfeatures:\n  F-A-001: covered\n  F-A-002: covered\n"))
st = run("gate.py", "status")["out"]
check("gate status counts done slices in CRLF files",
      re.search(r"next unfinished slice S3 \(pending\), 2/3 slices done", st) is not None, st)
git("checkout", "--", "locks")

# --- 2. CRLF: gate-guard still blocks under a locked gate ---------------------------------
lock_text = re.sub(r"^status: .*$", "status: locked", read("locks/gate-1.yaml"), count=1, flags=re.M)
w("locks/gate-1.yaml", crlf(lock_text))
guard = subprocess.run([sys.executable, os.path.join(PLUGIN, "hooks", "scripts", "gate_guard.py")],
                       input=json.dumps({"tool_input": {"file_path": os.path.join(wb, "matrix", "features.yaml")}, "cwd": wb}),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
check("gate-guard blocks an edit under a CRLF lock file", guard.returncode == 2,
      f"exit {guard.returncode}: {guard.stderr}")
git("checkout", "--", "locks")

# --- 3. numbered Acceptance criteria heading ----------------------------------------------
w("plan/specs/a.md", "---\ndomains: [a]\n---\n# A\n\n## 5. Acceptance criteria\n\n1. It works.\n")
v = run("validate.py")
check("validate reads `## 5. Acceptance criteria`",
      re.search(r"no `## Acceptance criteria` section", v["out"]) is None, v["out"][-800:])

# --- 4. descoped + feature_notes ----------------------------------------------------------
w("plan/progress.yaml", "slices:\n  S1: done\nfeatures:\n  F-A-001: covered\n  F-A-003: descoped\n"
  "feature_notes:\n  F-A-003: \"ruled out by the owner: no users\"\n")
v = run("validate.py")
check("validate accepts descoped with a note", v["code"] == 0, v["out"][-800:])
run("parity.py")
rep = read(f"parity/{date}.md")
check("parity leaves descoped out of the denominator",
      re.search(r"Coverage: 1/2 covered \(50%\).*1 descoped", rep) is not None, rep[:400])
check("parity lists descoped features with their reason",
      re.search(r"## Descoped[^\n]*\n- F-A-003 Feature 3 — ruled out by the owner", rep) is not None, rep)
w("plan/progress.yaml", "features:\n  F-A-003: descoped\n")
v = run("validate.py")
check("validate fails a descoped feature with no note",
      v["code"] != 0 and re.search(r"descoped with no reason.*F-A-003", v["out"]) is not None, v["out"][-800:])
w("plan/progress.yaml", "features:\n  F-A-001: covered\nfeature_notes:\n  F-A-009: x\n")
v = run("validate.py")
check("validate fails a feature_notes key that is not a feature",
      v["code"] != 0 and re.search(r"feature_notes: unknown feature F-A-009", v["out"]) is not None, v["out"][-800:])
w("plan/progress.yaml", "slices:\n  S1: done\n")
commit("eval fixtures")

# --- 5. upgrade: a CRLF re-checkout of a pristine copy is current --------------------------
w("scripts/erd.py", crlf(read("scripts/erd.py")))
up = run("upgrade.py", "--plugin", PLUGIN)["out"]
check("upgrade: a CRLF copy of a vendored file is not `modified`",
      re.search(r"LOCALLY MODIFIED[\s\S]*scripts/erd\.py", up.split("UNKNOWN")[0]) is None, up)
git("checkout", "--", "scripts/erd.py")

# --- 6. upgrade: a forced partial upgrade that breaks an import is named --------------------
# The workbench's acsuite gains two exports its own parity.py starts using, one through each
# import shape; forcing the plugin's acsuite over it, while parity stays local, removes the
# exports parity calls.
w("scripts/acsuite.py", read("scripts/acsuite.py") + "\n\ndef pick_run():\n    return None\n\n\ndef pick_other():\n    return None\n")
w("scripts/parity.py", read("scripts/parity.py") +
  "\ntry:\n    import acsuite as ac_lib\nexcept ImportError:\n    ac_lib = None\nif ac_lib:\n    ac_lib.pick_run()\n"
  "from acsuite import (\n    pick_other as other,\n)\n")
commit("local edits")
up = run("upgrade.py", "--plugin", PLUGIN, "--force", "scripts/acsuite.py")["out"]
check("upgrade names the import a forced file breaks (import x as y)",
      re.search(r"BROKEN IMPORTS[\s\S]*parity\.py \(this workbench\) uses `pick_run` from acsuite\.py \(plugin", up) is not None, up)
check("upgrade names the import a forced file breaks (from x import y)",
      re.search(r"parity\.py \(this workbench\) uses `pick_other` from acsuite\.py \(plugin", up) is not None, up)
pristine = run("upgrade.py", "--plugin", PLUGIN)["out"]
check("upgrade reports no broken import when nothing is forced", "BROKEN IMPORTS" not in pristine, pristine)
git("checkout", "HEAD~1", "--", "scripts/acsuite.py", "scripts/parity.py")
commit("undo local edits")

# --- 7. upgrade --apply warns when validate regresses --------------------------------------
# A local schema that accepts a status the plugin's does not: the workbench validates, then the
# forced plugin schema rejects its own data.
schema = json.loads(read("schemas/progress.schema.json"))
schema["properties"]["slices"]["additionalProperties"]["enum"].append("parked")
w("schemas/progress.schema.json", json.dumps(schema, indent=2, ensure_ascii=False) + "\n")
w("plan/progress.yaml", "slices:\n  S1: parked\n")
commit("local schema")
check("eval setup: the workbench validates before the upgrade", run("validate.py")["code"] == 0)
up = run("upgrade.py", "--plugin", PLUGIN, "--apply", "--force", "schemas/progress.schema.json")["out"]
check("upgrade --apply warns that validate now fails",
      re.search(r"WARNING[\s\S]*validate passed before this run and FAILS now", up) is not None, up[-1200:])
check("upgrade --apply prints how to undo it",
      re.search(r"git checkout -- .*schemas[/\\]progress\.schema\.json", up) is not None, up[-1200:])

if failures:
    print(f"\n{failures} failure(s). Workbench left at {wb}")
else:
    shutil.rmtree(base, ignore_errors=True)
    print("\nall passed")
sys.exit(1 if failures else 0)
