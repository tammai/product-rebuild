#!/usr/bin/env python3
"""migration_3.py (eval) — 3.0.0, spec 05 P1: does every 2.x capability in docs/MIGRATION-3.md have a 3.0 owner
and a test that passes there?

  python3 skills/rebuild-pipeline/eval/migration_3.py [--external]

WHY IT EXISTS. 3.0.0 deletes the 2.x mining, drafting and judging parts because rspec, sdlc and bug-hunter own
that work now. A capability nobody placed is lost silently, and a table row naming a test that does not pass is
a claim, not a placement. So each row's proof is run, not read.

What it checks:
  - every row of the capability table names an owner (rspec, sdlc, bug-hunter or this repo) and at least one proof;
  - every proof this repo owns (`eval/<file>.py [group]`) runs and exits 0, and a fixture proof exists;
  - every external proof is written `<repo>@<sha> <path>::<test>`.
With --external it also runs each external test from a `git archive` copy of that repo at the cited commit, so
nothing is written into the other repos. The repos are found through RSPEC_PLUGIN_ROOT, SDLC_PLUGIN_ROOT and
BUGHUNTER_PLUGIN_ROOT (each a git checkout); one that is not set, or not a checkout holding the commit, is
`not run`, and `not run` fails (design rule 6). rspec and sdlc run their tests with unittest, bug-hunter with
pytest, as each repo does.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
EVAL = os.path.join(ROOT, "skills", "rebuild-pipeline", "eval")
TABLE = os.path.join(ROOT, "docs", "MIGRATION-3.md")
OWNERS = ("rspec", "sdlc", "bug-hunter", "this repo")
ROOT_ENV = {"rspec": "RSPEC_PLUGIN_ROOT", "sdlc": "SDLC_PLUGIN_ROOT", "bug-hunter": "BUGHUNTER_PLUGIN_ROOT"}
LOCAL = re.compile(r"`eval/(\w+\.py)(?: (\w+))?`")
FIXTURE = re.compile(r"`fixture ([\w./-]+)`")
EXTERNAL = re.compile(r"`(rspec|sdlc|bug-hunter)@([0-9a-f]{7,40}) ([\w./-]+\.py)::(\w+)`")

failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'' if ok or not detail else chr(10) + '      ' + str(detail)}")
    if not ok:
        failures += 1


def rows():
    """(number, capability, owner cell, proof cell) for each row of the capability table."""
    with open(TABLE, encoding="utf-8") as f:
        text = f.read()
    out = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if len(cells) >= 5 and cells[0].isdigit():
            out.append((cells[0], cells[1], cells[2], cells[3]))
    return out


def run_local(cache, script, group):
    key = (script, group)
    if key not in cache:
        r = subprocess.run([sys.executable, os.path.join(EVAL, script), *([group] if group else [])], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        cache[key] = (r.returncode, (r.stdout + r.stderr).strip()[-400:])
    return cache[key]


def run_external(repo, sha, path, test, trees):
    root = os.environ.get(ROOT_ENV[repo])
    if not root:
        return False, f"not run: {ROOT_ENV[repo]} is not set"
    if (repo, sha) not in trees:
        r = subprocess.run(["git", "-C", root, "archive", "--format=tar", sha], capture_output=True)
        if r.returncode:
            trees[(repo, sha)] = None
        else:
            d = tempfile.mkdtemp(prefix=f"migration-{repo}-")
            with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
                t.extractall(d)
            trees[(repo, sha)] = d
    d = trees[(repo, sha)]
    if not d:
        return False, f"not run: {root} has no commit {sha}"
    if repo == "bug-hunter":
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"{path}::{test}"]
    else:
        # discover, as rspec's and sdlc's own test command runs them: their tests import `helpers` from tests/.
        folder, name = os.path.split(path)
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", folder or ".", "-t", folder or ".", "-p", name, "-k", test]
    r = subprocess.run(cmd, cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    out = (r.stdout + r.stderr).strip()
    ran = not re.search(r"\bRan 0 tests\b|no tests ran|not found", out)
    return r.returncode == 0 and ran, out[-400:]


def main():
    external = "--external" in sys.argv[1:]
    if not os.path.exists(TABLE):
        check("docs/MIGRATION-3.md exists", False)
        return 1
    table = rows()
    check("the capability table has rows", len(table) > 0)
    cache, trees = {}, {}
    try:
        for num, cap, owner, proof in table:
            label = f"{num}. {cap[:70]}"
            owners = [o for o in OWNERS if o in owner]
            locals_ = LOCAL.findall(proof)
            fixtures = FIXTURE.findall(proof)
            externals = EXTERNAL.findall(proof)
            check(f"{label}: has an owner and a proof", bool(owners) and bool(locals_ or fixtures or externals),
                  f"owner {owner!r}, proof {proof!r}")
            for script, group in locals_:
                code, out = run_local(cache, script, group)
                check(f"{label}: eval/{script}{' ' + group if group else ''} passes", code == 0, out)
            for rel in fixtures:
                check(f"{label}: fixture {rel} exists", os.path.exists(os.path.join(ROOT, rel)))
            for repo, sha, path, test in externals:
                if external:
                    ok, out = run_external(repo, sha, path, test, trees)
                    check(f"{label}: {repo}@{sha[:7]} {path}::{test} passes", ok, out)
            stray = re.sub(r"`(eval/|fixture |(rspec|sdlc|bug-hunter)@)[^`]*`", "", proof)
            check(f"{label}: every proof is written in a form this eval reads", "`" not in stray, proof)
    finally:
        for d in trees.values():
            if d:
                shutil.rmtree(d, ignore_errors=True)
    print(f"\n{failures} failure(s)." if failures else "\nall passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
