#!/usr/bin/env python3
"""contracts_v1.py (eval) — 3.0 W1: is contracts/v1/ intact, and does vendor-check catch drift?

  python3 skills/rebuild-pipeline/eval/contracts_v1.py

WHY IT EXISTS. contracts/v1/ is copied byte-identical into rspec, sdlc and bug-hunter (decision D1),
and every one of them trusts MANIFEST to say the copy is unchanged. This repo is the canonical home,
so it runs the same drift check the consumers run (`contracts.py vendor-check`), then proves the
check bites: a changed byte, a missing file, an extra file and a missing header each fail it.
It also runs contracts/v1/test_contracts.py, because the project's test command runs eval/*.py
and those unit tests would otherwise run nowhere.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
V1 = os.path.join(ROOT, "contracts", "v1")
TOOL = os.path.join(V1, "contracts.py")

failures = 0


def check(name, ok, detail=""):
    global failures
    print(("ok    " if ok else "FAIL  ") + name)
    if not ok:
        failures += 1
        if detail:
            print("      " + detail.strip().replace("\n", "\n      "))


def vendor_check(folder):
    p = subprocess.run([sys.executable, TOOL, "vendor-check", folder], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def tampered(change):
    tmp = tempfile.mkdtemp(prefix="contracts-v1-eval-")
    copy = os.path.join(tmp, "v1")
    shutil.copytree(V1, copy, ignore=shutil.ignore_patterns("__pycache__"))
    change(copy)
    code, out = vendor_check(copy)
    shutil.rmtree(tmp)
    return code, out


def append(path, data):
    with open(path, "ab") as f:
        f.write(data)


def strip_header_and_reseal(copy):
    path = os.path.join(copy, "CONTRACTS.md")
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(data.split(b"\n", 1)[1])
    subprocess.run([sys.executable, os.path.join(copy, "contracts.py"), "seal", copy], check=True,
                   capture_output=True)


code, out = vendor_check(V1)
check("the committed contracts/v1 passes vendor-check", code == 0, out)

code, out = tampered(lambda c: append(os.path.join(c, "CONTRACTS.md"), b" "))
check("a changed byte fails it, naming the file", code != 0 and "CONTRACTS.md" in out, out)

code, out = tampered(lambda c: os.remove(os.path.join(c, "finding.schema.json")))
check("a missing file fails it", code != 0 and "finding.schema.json" in out, out)

code, out = tampered(lambda c: append(os.path.join(c, "extra.py"), b"# contracts-version: 1.0.0\n"))
check("an extra file fails it", code != 0 and "extra.py" in out, out)

code, out = tampered(strip_header_and_reseal)
check("a file without its contracts-version header fails it", code != 0 and "header" in out, out)

p = subprocess.run([sys.executable, os.path.join(V1, "test_contracts.py")], capture_output=True, text=True)
check("contracts/v1 unit tests pass", p.returncode == 0, p.stderr[-3000:])

print("\n%d failure(s)." % failures if failures else "\nall passed.")
sys.exit(1 if failures else 0)
