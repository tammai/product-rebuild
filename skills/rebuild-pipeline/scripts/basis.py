#!/usr/bin/env python3
"""basis.py — evidence-basis checks shared by validate.py and parity.py. Library, not an
entry point. Needs yamlio (and through it the vendored PyYAML); gate.py never imports it, so
unlike erd.py this one is allowed that dependency.

`basis` answers a different question from `confidence`, and conflating them is the mistake
this field exists to stop. `confidence` is the MINER's certainty. `basis` is WHERE THE FACT
CAME FROM. A route transcribed from a migration file at the pinned commit and a route
inferred from a docs page can both be recorded `confidence: high` — the miner is equally
sure in both cases — and G4b should not treat them the same when it freezes a contract.

Result shapes are dicts with snake_case keys (`total_evidence`, `total_missing`, `any_basis`,
`finding_ids`, `inferred_only`).
"""
from __future__ import annotations

import os
import re

import yamlio


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


def _js_str(v):
    """Coerce a free-text evidence pointer the way the Node twin's String() did."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    if isinstance(v, list):
        return ",".join("" if x is None else _js_str(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


def _get(obj, key):
    return obj.get(key) if isinstance(obj, dict) else None


def _hashable(v):
    try:
        hash(v)
        return True
    except TypeError:
        return False


# Where a fact came from. Orthogonal to `confidence`.
BASIS_VALUES = ["transcribed", "observed", "inferred"]

# One line each, so every file that explains this says the same thing.
BASIS_MEANING = {
    "transcribed": "copied from the reference's source at the pinned commit (schema files, route tables, call sites)",
    "observed": "seen at runtime on the running reference or a device restored from a real backup",
    "inferred": "derived from docs, changelogs, API responses, or reasoning",
}


def is_pre_basis_workbench(root="."):
    """True for workbenches scaffolded before `basis` became a required field. They get warnings
    where a new workbench gets errors — the same treatment, and the same signal
    (`locks/pipeline.yaml`'s schema_version), that erd.py and playbook.py use.

    The grace this encodes is real rather than calendar-based: a project mid-mining when this
    landed has findings written under the old rule, and the non-goal was always "no backfill"."""
    p = _join(root, "locks", "pipeline.yaml")
    if not os.path.exists(p):
        return True
    m = re.search(r'^schema_version:\s*"?([0-9.]+)"?', _read_text(p), re.M)
    if not m:
        return True
    parts = [int(x) if x else 0 for x in m.group(1).split(".")]
    # A one-part version has no minor: the Node twin compared `undefined < 4`, which is false.
    return parts[0] == 0 and len(parts) > 1 and parts[1] < 4


def finding_files(root="."):
    """Every schema-validated finding file. `nfr-profile.yaml` is free-form and excluded."""
    d = _join(root, "findings")
    if not os.path.exists(d):
        return []
    out = []
    for dirpath, _dirs, names in os.walk(d):
        for n in names:
            f = os.path.normpath(os.path.join(dirpath, n))
            if (n.endswith(".yaml") or n.endswith(".yml")) and os.path.isfile(f) \
                    and not f.endswith("nfr-profile.yaml"):
                out.append(f)
    return sorted(out)


def _read_findings(file):
    """Parse one findings file into a list, tolerating anything that is not one."""
    try:
        data = yamlio.load(_read_text(file))
    except Exception:
        return None
    return data if isinstance(data, list) else None


def check_basis(root="."):
    """Per-file basis coverage. `unparseable` and non-list files are skipped rather than
    reported — their own schema pass in validate.py already owns that failure, and reporting
    it twice trains people to read one of the two messages as noise."""
    files = []
    total_evidence = total_missing = 0
    any_basis = False
    for file in finding_files(root):
        findings = _read_findings(file)
        if findings is None:
            continue
        evidence = missing = 0
        ids = []
        for f in findings:
            ev = _get(f, "evidence")
            for e in (ev if isinstance(ev, list) else []):
                evidence += 1
                if isinstance(e, dict) and e.get("basis") in BASIS_VALUES:
                    any_basis = True
                else:
                    missing += 1
                    fid = _get(f, "id")
                    if fid and fid not in ids:
                        ids.append(fid)
        if not evidence:
            continue
        files.append({"file": file, "evidence": evidence, "missing": missing, "finding_ids": ids})
        total_evidence += evidence
        total_missing += missing
    return {"files": files, "total_evidence": total_evidence, "total_missing": total_missing, "any_basis": any_basis}


def feature_basis(root="."):
    """Join the feature matrix to the findings that back it, then report the basis behind each
    feature. A feature whose ONLY basis is `inferred` is the weakest parity claim in the
    report — nobody transcribed it from source and nobody watched it happen.

    Returns a function `features -> {"inferred_only": [...], "unjoined": [...]}`.

    The join is the awkward part and it is worth being explicit about, because a silent one
    would be worse than none. `feature.evidence` is an array of free-text pointers (the schema
    says `string`), so three matches are tried per pointer, in order: the pointer IS a finding
    id; the pointer equals a finding evidence `url` or `path`; a `[a-z0-9-]+` token inside the
    pointer is a finding id. Anything that matches nothing is counted and REPORTED as unjoined
    rather than quietly treated as "not inferred" — a zero that came from a failed join reads
    exactly like a clean bill of health, which is the one thing this must not do."""
    by_id, by_pointer = {}, {}
    for file in finding_files(root):
        for f in _read_findings(file) or []:
            fid = _get(f, "id")
            if not fid or not _hashable(fid):
                continue
            ev = f.get("evidence")
            evidence = ev if isinstance(ev, list) else []
            bases = [_get(e, "basis") for e in evidence if _get(e, "basis") in BASIS_VALUES]
            rec = {"id": fid, "bases": bases}
            by_id[fid] = rec
            for e in evidence:
                if _get(e, "url"):
                    by_pointer[_js_str(e["url"])] = rec
                if _get(e, "path"):
                    by_pointer[_js_str(e["path"])] = rec

    def matches_for(pointers):
        hits = {}
        for raw in pointers:
            p = _js_str("" if raw is None else raw).strip()
            if not p:
                continue
            direct = by_id.get(p) or by_pointer.get(p)
            if direct:
                hits[direct["id"]] = direct
                continue
            for tok in re.findall(r"[a-z0-9][a-z0-9-]*", p.lower()):
                rec = by_id.get(tok)
                if rec:
                    hits[rec["id"]] = rec
        return list(hits.values())

    def join_features(features):
        inferred_only, unjoined = [], []
        for f in features:
            def lst(v):
                return v if isinstance(v, list) else []
            matched = matches_for([
                *lst(_get(f, "evidence")),
                *lst(_get(f, "flows")),
                *lst(_get(_get(f, "history"), "evidence")),
            ])
            if not matched:
                unjoined.append(f)
                continue
            bases = {b for m in matched for b in m["bases"]}
            if not bases:
                continue                       # findings predate the field — say nothing
            if bases == {"inferred"}:
                inferred_only.append(f)
        return {"inferred_only": inferred_only, "unjoined": unjoined}

    return join_features


# One-line remedy, shared so every caller says the same thing.
BASIS_REMEDY = (
    f"Add `basis:` to each evidence entry — {' | '.join(BASIS_VALUES)} "
    f"(see references/g1-mining.md, \"Where a fact came from\"). It records the SOURCE of the fact, "
    f"not the miner's certainty; `confidence` still does that.")
