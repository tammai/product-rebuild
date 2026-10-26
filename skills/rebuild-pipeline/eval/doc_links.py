#!/usr/bin/env python3
"""doc_links.py (eval) — does every reference doc the plugin names exist, and every script it says to run?

  python3 skills/rebuild-pipeline/eval/doc_links.py

WHY IT EXISTS. g5-build.md was split in 1.4.0, and about 35 places named its sections: hook messages the
user reads when a guard blocks, script comments, other docs. A rename or split that leaves one of them
pointing at a file that is not there fails silently and shows up as a person following an instruction to
nothing. This reads the plugin's own text for names like `g5-build.md` and `python3 scripts/boundary.py` and
checks each resolves to a file in this repo. It does not check section names inside a file.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.realpath(os.path.join(HERE, "..", "..", ".."))
REFS = os.path.join(ROOT, "skills", "rebuild-pipeline", "references")
SCRIPTS = os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts")
SKIP_DIRS = {".git", "_vendor", "specs", "eval", "node_modules", "__pycache__", "licenses"}

ref_names = {n for n in os.listdir(REFS) if n.endswith(".md")}
script_names = {n for n in os.listdir(SCRIPTS) if n.endswith(".py")}
rubric_names = {n for n in os.listdir(os.path.join(REFS, "rubrics"))}
failures = []
checked = 0

for dirpath, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for f in files:
        if not f.endswith((".md", ".py", ".json", ".sh")) or f == "CHANGELOG.md":
            continue
        path = os.path.join(dirpath, f)
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        rel = os.path.relpath(path, ROOT)
        for m in re.finditer(r"(?<![\w/.-])(g[0-6p](?:-[a-z0-9]+)+\.md|subagent-briefs\.md|autopilot\.md|g0-reference\.md|architecture-default\.md)\b", text):
            checked += 1
            if m.group(1) not in ref_names:
                failures.append(f"{rel}: names reference doc {m.group(1)}, which does not exist")
        for m in re.finditer(r"python3 (?:\$\{CLAUDE_PLUGIN_ROOT\}/skills/rebuild-pipeline/)?scripts/([a-z_]+\.py)", text):
            checked += 1
            if m.group(1) not in script_names:
                failures.append(f"{rel}: tells the reader to run scripts/{m.group(1)}, which does not exist")

for n in failures:
    print("FAIL  " + n)
print(f"{checked} reference(s) checked.")
print(f"\n{len(failures)} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
