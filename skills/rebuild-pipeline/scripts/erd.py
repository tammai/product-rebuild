#!/usr/bin/env python3
"""erd.py — data-model checks shared by validate.py and gate.py. Library, not an entry point.
Standard library only by necessity: gate.py runs without the workbench's vendored YAML code.

Deliberately NOT a Mermaid parser. It answers the two questions Gate 4 actually gates
on — is there a data model at all, and does it declare entities — because the failure
worth catching is a scaffold stub. A file containing the word `erDiagram` and nothing
else satisfies "has an erDiagram block" forever, so that check alone can never fail.

Result shapes are dicts with snake_case keys (`per_file`).
"""
from __future__ import annotations

import os
import re


# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's _read_text for the incident.
def _read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        return re.sub(r"\r\n?", "\n", fh.read())


def _join(*parts):
    # normpath: paths appear verbatim in messages, and `join(".", x)` must read `x`, not `./x`.
    return os.path.normpath(os.path.join(*parts))


# Directory holding one Mermaid erDiagram per bounded context.
DATA_MODEL_DIR = "contracts/data-model"


def is_legacy_workbench(root="."):
    """True for workbenches scaffolded before the data model became a checked artifact.
    They get warnings where a new workbench gets errors.

    The signal is `locks/pipeline.yaml`, not gate-4's `protects:`. Every workbench ever
    scaffolded protects `contracts/` wholesale and gate.py hashes every file beneath it,
    so `protects` already covers the new file everywhere and cannot tell old from new."""
    p = _join(root, "locks", "pipeline.yaml")
    if not os.path.exists(p):
        return True
    m = re.search(r'^schema_version:\s*"?([0-9.]+)"?', _read_text(p), re.M)
    if not m:
        return True
    parts = [int(x) if x else 0 for x in m.group(1).split(".")]
    # A one-part version has no minor: the Node twin compared `undefined < 2`, which is false.
    return parts[0] == 0 and len(parts) > 1 and parts[1] < 2


# An entity reference: a bare name, a quoted name, or either carrying a display alias
# (`PROJECT["Project"]`). The alias form is valid Mermaid and a hand-written diagram is
# where it shows up — a pattern that misses it reports "declares no entities" on a correct
# file, which blocks a gate lock. A check with false positives on legitimate work gets
# disabled within a week, so it has to match what people actually write.
_NAME = r'(?:[A-Za-z_][A-Za-z0-9_-]*|"[^"]+")(?:\[[^\]]*\])?'
# `CUSTOMER ||--o{ ORDER : places` — the cardinality token is what marks a relationship.
_REL = re.compile(r"^\s*(" + _NAME + r")\s*([|}o{<>.-]{3,})\s*(" + _NAME + r")\s*:")
# `CUSTOMER {` opens an attribute block.
_BLOCK = re.compile(r"^\s*(" + _NAME + r")\s*\{\s*\Z")


def _entity_name(s):
    # Entities are keyed by name, so the alias must not make `PROJECT` and `PROJECT["x"]` two.
    return re.sub(r"\[[^\]]*\]\Z", "", s)


def read_erd(file):
    """Read one .mermaid file. Returns the entity names it declares, how many relationships
    it draws, and any problems. Unrecognized lines (`direction`, `title`, frontmatter) are
    ignored rather than reported — this is a floor check, not a linter."""
    problems, entities = [], set()
    relationships, in_block, saw_header = 0, False, False
    for raw in _read_text(file).split("\n"):
        line = re.sub(r"%%.*\Z", "", raw, count=1)  # Mermaid comment
        if not line.strip():
            continue
        if in_block:
            if re.match(r"\s*\}", line):
                in_block = False
            continue
        if re.match(r"\s*erDiagram\b", line, re.A):
            saw_header = True
            continue
        rel = _REL.match(line)
        if rel:
            entities.add(_entity_name(rel.group(1)))
            entities.add(_entity_name(rel.group(3)))
            relationships += 1
            continue
        block = _BLOCK.match(line)
        if block:
            entities.add(_entity_name(block.group(1)))
            in_block = True
    if not saw_header:
        problems.append("no `erDiagram` block")
    elif not entities:
        problems.append("`erDiagram` block declares no entities")
    return {"entities": entities, "relationships": relationships, "problems": problems}


def check_data_model(root="."):
    """Check every data model in the workbench. `missing` is reported separately from
    `problems` because an absent data model is legitimate until Gate 4 — callers decide
    when it becomes fatal."""
    d = _join(root, DATA_MODEL_DIR)
    files = []
    if os.path.exists(d):
        for dirpath, _dirs, names in os.walk(d):
            for n in names:
                f = os.path.join(dirpath, n)
                if n.endswith(".mermaid") and os.path.isfile(f):
                    files.append(os.path.normpath(f))
        files.sort()
    problems, per_file = [], []
    for f in files:
        r = read_erd(f)
        per_file.append({"file": f, **r})
        for p in r["problems"]:
            problems.append(f"{f}: {p}")
    return {"files": files, "per_file": per_file, "problems": problems, "missing": len(files) == 0}


# One-line remedy, shared so both scripts say the same thing.
DATA_MODEL_REMEDY = (
    f"Draft the data model first: one Mermaid erDiagram per bounded context at "
    f"{DATA_MODEL_DIR}/<context>.mermaid (see contracts/data-model/README.md).")
