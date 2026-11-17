#!/usr/bin/env python3
"""upgrade_manifest_keys.py (eval): upgrade.py finds a vendored file's recorded hash whichever path
separator the manifest key was written with.

  python3 skills/rebuild-pipeline/eval/upgrade_manifest_keys.py

WHY IT EXISTS. On Windows, upgrade.py looked up `locks/tooling.json` keys with backslash paths
while rebuild_init.py writes them with forward slashes. Every locally edited file came out as
UNKNOWN PROVENANCE instead of LOCALLY MODIFIED, so the user could not tell their own patches from
old copies (the Kanso CRM rebuild's 3.2.1 upgrade refused 5 files that way). The backslash-keyed
manifest an older upgrade.py wrote on Windows is a case too, so this eval fails on a POSIX host as
well as on Windows. It is its own file because windows_and_upgrade.py has a known failure on
Windows (.sdlc/baseline.md), which would hide whether this case passes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, "..", "scripts"))
PLUGIN = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
base = tempfile.mkdtemp(prefix="upgrade-keys-eval-")
subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "evalwb", "--dir", base],
               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
wb = os.path.join(base, "evalwb-workbench")
MANIFEST = os.path.join(wb, "locks", "tooling.json")
failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


def upgrade(*args):
    r = subprocess.run([sys.executable, os.path.join("scripts", "upgrade.py"), "--plugin", PLUGIN, *args], cwd=wb,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return r.stdout + r.stderr


def section(out, heading):
    m = re.search(rf"^{heading}[^\n]*\n((?:  [^\n]*\n)*)", out, re.M)
    return m.group(1) if m else ""


def listed(out, heading, rel):
    return re.search(rf"^  scripts[/\\]{re.escape(rel)}\b", section(out, heading), re.M) is not None


with open(os.path.join(wb, "scripts", "flows.py"), "a", encoding="utf-8") as fh:
    fh.write("\n# a local patch\n")

out = upgrade()
check("a file edited here is LOCALLY MODIFIED, not UNKNOWN PROVENANCE, with the manifest rebuild_init wrote",
      listed(out, "LOCALLY MODIFIED", "flows.py") and not listed(out, "UNKNOWN PROVENANCE", "flows.py"), out)

with open(MANIFEST, encoding="utf-8") as fh:
    mf = json.load(fh)
mf["files"] = {k.replace("/", "\\"): v for k, v in mf["files"].items()}
with open(MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(mf, fh, indent=2)
out = upgrade()
check("…and with backslash keys, as an older upgrade.py wrote them on Windows",
      listed(out, "LOCALLY MODIFIED", "flows.py") and not listed(out, "UNKNOWN PROVENANCE", "flows.py"), out)

upgrade("--keep", "scripts/flows.py")
with open(MANIFEST, encoding="utf-8") as fh:
    kept = json.load(fh).get("kept") or {}
out = upgrade()
check("--keep records the file under a forward-slash key, and the next run reports it KEPT",
      list(kept) == ["scripts/flows.py"] and listed(out, "KEPT", "flows.py"), json.dumps(kept) + "\n" + out)

if failures:
    print(f"\n{failures} failure(s). Workbench left at {wb}")
else:
    shutil.rmtree(base, ignore_errors=True)
    print("\nall passed")
sys.exit(1 if failures else 0)
