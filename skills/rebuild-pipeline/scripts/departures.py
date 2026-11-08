#!/usr/bin/env python3
"""departures.py — the one registry of accepted differences, `docs/departures.yaml` (contracts C5, spec 05 P7).
A library for the workbench scripts that read or add a departure; run it alone to list the registry.

  python3 scripts/departures.py            # every departure, and which are still `proposed`

WHY ONE MODULE. 2.x kept accepted differences in four places (a slice's `departures:`, parity/flows/DECISIONS.md,
parity/equiv/DECISIONS.md, and the slice reviews), so a difference accepted for one check failed the next. Every
reader now asks this module, and every writer appends through it: holdout.py, route.py, equiv.py, flows.py and
gate.py's Gate 5 check, plus bug-hunter (which reads the YAML itself).

WHAT EXPLAINS A DIFFERENCE. Only a decided departure: one with `decided_by`, not `status: proposed` (C5: autopilot
may propose, never decide; a proposed entry blocks the gate that reads it). It explains a criterion it names in
`criteria`, a value its `match` rule covers (`{runner, pointer, rule}`; rules `regex:<re>`, `uuid`, `int`,
`iso8601`, `any`), or an equivalence trace named by the rule `equiv-trace:<name>`, which `equiv.py accept` writes.

ADDING ONE AFTER GATE 1. Gate 1 hashes departures.yaml (05 P2), so a departure appended after the gate-1 lock
would break that lock. Until the user decides whether the registry stays under that hash (an open spec question,
2026-11-09), append() refuses then, with nothing written. That rule lives only in gate1_allows_append(): change
it there.

Standard library plus the vendored yamlio, like every script here that reads YAML.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import yamlio  # noqa: E402

PATH = os.path.join("docs", "departures.yaml")
KINDS = ("simplification", "deliberate-change", "reference-defect-not-copied", "environment", "branding")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?\Z")


def _text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        return re.sub(r"\r\n?", "\n", fh.read())


def load(root="."):
    """Every entry, or [] when there is no registry. An unreadable one raises: a check must not read it as empty."""
    p = os.path.join(root, PATH)
    if not os.path.exists(p):
        return []
    data = yamlio.load(_text(p))
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{PATH} is not a list of departures")
    return [d for d in data if isinstance(d, dict)]


def decided(root="."):
    return [d for d in load(root) if d.get("decided_by") and d.get("status", "accepted") != "proposed"]


def proposed(root="."):
    return [d for d in load(root) if d.get("status") == "proposed"]


def explained_by(cid, root="."):
    """for_criterion() for a check that must keep running: an unreadable registry explains nothing, and the
    caller is told once on stderr instead of crashing mid-run."""
    try:
        return for_criterion(cid, root)
    except Exception as e:
        global _warned
        if not _warned:
            print(f"warning: {PATH} could not be read ({e}); no difference counts as explained.", file=sys.stderr)
            _warned = True
        return None


_warned = False


def for_criterion(cid, root="."):
    """The id of a decided departure naming this criterion, or None."""
    return next((d["id"] for d in decided(root) if cid in (d.get("criteria") or [])), None)


def _rule_ok(rule, value):
    s = "" if value is None else str(value)
    if rule == "any":
        return True
    if rule == "uuid":
        return bool(UUID.match(s))
    if rule == "int":
        return re.fullmatch(r"-?\d+", s) is not None
    if rule == "iso8601":
        return bool(ISO.match(s))
    if rule.startswith("regex:"):
        try:
            return re.search(rule[len("regex:"):], s) is not None
        except re.error:
            return False
    return False


def for_value(runner, pointer, value, criterion=None, root="."):
    """The id of a decided departure whose match rule covers this observed value, or None. A rule scoped by the
    departure's `criteria` applies only to those criteria."""
    for d in decided(root):
        crits = d.get("criteria") or []
        if criterion and crits and criterion not in crits:
            continue
        for m in d.get("match") or []:
            if (isinstance(m, dict) and m.get("runner") == runner and m.get("pointer") in (None, pointer)
                    and _rule_ok(str(m.get("rule", "")), value)):
                return d["id"]
    return None


def for_trace(name, root="."):
    """The id of a decided departure accepting this equivalence trace (rule `equiv-trace:<name>`), or None."""
    for d in decided(root):
        for m in d.get("match") or []:
            if isinstance(m, dict) and m.get("rule") == f"equiv-trace:{name}":
                return d["id"]
    return None


def gate1_allows_append(root="."):
    """(allowed, why). The one place that decides whether a departure may be added now (see the module doc)."""
    lock = os.path.join(root, "locks", "gate-1.yaml")
    if os.path.exists(lock) and re.search(r"^status: locked$", _text(lock), re.M) and \
            re.search(r"^  - docs/departures\.yaml$", _text(lock), re.M):
        return False, ("gate-1 is locked and hashes docs/departures.yaml, so adding a departure would break that lock. "
                       "Reopen gate-1 with the user (python3 scripts/gate.py reopen gate-1 --reason \"...\"), add it, and "
                       "lock again; whether later departures need this is an open decision for the user.")
    return True, ""


def next_id(entries):
    nums = [int(m.group(1)) for d in entries for m in [re.match(r"^D-(\d+)$", str(d.get("id", "")))] if m]
    return f"D-{(max(nums) + 1 if nums else 1):03d}"


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def append(kind, summary, decided_by, criteria=(), features=(), match=(), root="."):
    """Append one decided departure; returns its id, or raises ValueError with nothing written."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not decided_by or not str(decided_by).strip():
        raise ValueError("a departure needs decided_by: who decided it (contracts C5)")
    ok, why = gate1_allows_append(root)
    if not ok:
        raise ValueError(why)
    entries = load(root)
    did = next_id(entries)
    lines = [f"- id: {did}", f"  kind: {kind}"]
    if criteria:
        lines.append(f"  criteria: [{', '.join(criteria)}]")
    if features:
        lines.append(f"  features: [{', '.join(features)}]")
    lines.append(f"  summary: {_q(summary)}")
    if match:
        lines.append("  match:")
        lines += ["    - {" + ", ".join(f"{k}: {_q(v)}" for k, v in m.items()) + "}" for m in match]
    lines.append(f"  decided_by: {_q(decided_by)}")
    p = os.path.join(root, PATH)
    text = _text(p) if os.path.exists(p) else ""
    if re.fullmatch(r"\s*(#.*\n\s*)*\[\]\s*", text or "[]"):
        text = re.sub(r"\[\]\s*\Z", "", text)  # an empty flow list becomes the first block item
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text.rstrip("\n") + ("\n" if text.strip() else "") + "\n".join(lines) + "\n")
    return did


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    for d in load():
        state = "PROPOSED" if d.get("status") == "proposed" else ("decided" if d.get("decided_by") else "NO decided_by")
        print(f"{d.get('id')}  {state:9}  {d.get('kind')}  {d.get('summary')}")
