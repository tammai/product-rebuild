#!/usr/bin/env python3
"""evidence_bundle.py (eval) — is a bundle excerpt byte-for-byte the file's lines, and are bad specs refused?

  python3 skills/rebuild-pipeline/eval/evidence_bundle.py

The point of the script is that an excerpt is verbatim, which a model retyping it is not. So this checks an
excerpt against the file it came from (including a tab, trailing spaces and a CRLF file), that a range past
the end is clamped and says so, and that a missing file, a path outside the workbench, and a range that
starts past the end each write nothing.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

SCRIPTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "scripts")
failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


base = tempfile.mkdtemp(prefix="bundle-eval-")
subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "eb", "--dir", base],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
wb = os.path.join(base, "eb-workbench")
text = "".join(f"line {i}\twith tab and trailing  \n" if i % 2 else f"line {i} plain\n" for i in range(1, 21))
os.makedirs(os.path.join(wb, "contracts"), exist_ok=True)
with open(os.path.join(wb, "contracts", "a.yaml"), "w", newline="") as f:
    f.write(text)
with open(os.path.join(wb, "contracts", "crlf.yaml"), "w", newline="") as f:
    f.write("x: 1\r\ny: 2\r\nz: 3\r\n")


def run(*a):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "evidence_bundle.py"), *a], cwd=wb, capture_output=True, text=True,
                          encoding="utf-8")


out = os.path.join(wb, "plan", "gate-reviews", "gate-4-evidence.md")
r = run("--out", "plan/gate-reviews/gate-4-evidence.md", "contracts/a.yaml:3-6", "contracts/crlf.yaml")
bundle = open(out, encoding="utf-8", newline="").read()
want = "".join(text.splitlines(True)[2:6])
check("it runs", r.returncode == 0, r.stderr)
check("a range is copied byte for byte (tabs and trailing spaces kept), under a path:start-end heading",
      "## contracts/a.yaml:3-6\n\n```\n" + want.rstrip("\n") + "\n```" in bundle, bundle)
check("a whole file is copied with CRLF folded to LF", "```\nx: 1\ny: 2\nz: 3\n```" in bundle and "\r" not in bundle)
r = run("--out", "plan/gate-reviews/clamp.md", "contracts/a.yaml:15-99")
check("a range past the end is clamped and the heading says so", r.returncode == 0 and "contracts/a.yaml:15-20 (clamped: the file has 20 lines)" in
      open(os.path.join(wb, "plan/gate-reviews/clamp.md")).read())
for label, spec in (("a missing file", "contracts/none.yaml:1-2"), ("a path outside the workbench", "../" + os.path.basename(base) + "/eb-workbench/../x"),
                    ("a range starting past the end", "contracts/a.yaml:50-60"), ("a bad range", "contracts/a.yaml:9-3")):
    dest = os.path.join(wb, "plan", f"refused-{abs(hash(label))}.md")
    r = run("--out", dest, spec)
    check(f"{label} is refused and writes nothing", r.returncode == 1 and not os.path.exists(dest), r.stderr)
check("no arguments prints usage", run().returncode == 1)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
