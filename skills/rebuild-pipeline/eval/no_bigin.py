#!/usr/bin/env python3
"""no_bigin.py (eval) — E22: has anything started depending on bigin-skills again?

  python3 skills/rebuild-pipeline/eval/no_bigin.py

WHY IT EXISTS. The dependency spread to 13 files because each mention looked harmless on its own: a
doc naming the plugin that creates repos, a comment saying a table was copied from its router, an
agent called `bigin-skills:worker`. By the time anyone counted, repo creation, lane dispatch, the
guards and the model ladder all assumed it was installed. This fails on any new mention, so the next
one is caught in the edit that adds it and not in the audit that finds a dozen.

It looks for the names of the retired plugin and its skills, and for this plugin's own old name. It
does not look for the bare word "bigin", which is a company and an email domain.

WHAT IS ALLOWED, and why each is: CHANGELOG.md and specs/ (history: they say what was removed);
NOTICE.md and licenses/ (the provenance of ported code is a legal notice, not a dependency); this
file; and two lines that tell a user the old plugin exists, so that someone holding a 0.x rebuild is
sent to it instead of left guessing.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

FORBIDDEN = re.compile(r"bigin-skills|bigin-harness|bigin_harness|task-workflow|model-router|product-rebuild-skills")
SKIP_PATHS = re.compile(r"^(CHANGELOG\.md|NOTICE\.md|specs/|licenses/|\.git/|skills/rebuild-pipeline/eval/no_bigin\.py$|"
                        r"skills/rebuild-pipeline/scripts/_vendor/)")
# The only places the old plugin may be named, each identified by what the line says.
POINTERS = (
    ("README.md", re.compile(r"formerly published as `product-rebuild-skills`")),
    ("skills/rebuild-pipeline/SKILL.md", re.compile(r"`product-rebuild-skills`, the plugin this one replaced")),
)

files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout.split("\n")
hits, scanned = [], 0
for rel in files:
    if not rel or SKIP_PATHS.search(rel) or not os.path.isfile(os.path.join(ROOT, rel)):
        continue
    try:
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    except (UnicodeDecodeError, OSError):
        continue  # a binary file (the pipeline diagram) names nothing
    scanned += 1
    for n, line in enumerate(text.split("\n"), 1):
        m = FORBIDDEN.search(line)
        if not m:
            continue
        if any(rel == p and rx.search(line) for p, rx in POINTERS):
            continue
        hits.append(f"{rel}:{n}: {m.group(0)} — {line.strip()[:100]}")

print(f"scanned {scanned} files")
if hits:
    print(f"FAIL  {len(hits)} reference(s) to the retired plugin or the old name:")
    for h in hits:
        print("      " + h)
    sys.exit(1)
print("ok    no reference to bigin-skills, its skills, or this plugin's old name outside history and notices")
