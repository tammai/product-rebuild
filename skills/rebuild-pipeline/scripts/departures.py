#!/usr/bin/env python3
"""departures.py — the one registry of accepted differences, `docs/departures.yaml` (contracts C5, spec 05 P7).
A library for the workbench scripts that read or add a departure; run it alone to list the registry.

  python3 scripts/departures.py            # every departure, and which are still `proposed`

WHY ONE MODULE. 2.x kept accepted differences in four places (a slice's `departures:`, parity/flows/DECISIONS.md,
parity/equiv/DECISIONS.md, and the slice reviews), so a difference accepted for one check failed the next. Every
reader now asks this module, and every writer appends through it: holdout.py, route.py, equiv.py, flows.py and
gate.py's Gate 5 check, plus bug-hunter (which reads the YAML itself).

WHAT EXPLAINS A DIFFERENCE. Only a decided departure: one with `decided_by`, not `status: proposed` (C5: autopilot
may propose, never decide; a proposed entry blocks the gate that reads it), and only when one of its `match` rules
matches the observed difference (`{runner, pointer, rule}`; rules `regex:<re>`, `uuid`, `int`, `iso8601`, `any`;
an HTTP status is pointer `status`). Its `criteria`, when given, scope the rules to those criteria. A departure
with `match: []` is human-only (C5): it explains a criterion it names only when that criterion is Drop in
criteria.lock.json, never a failure of a live one. Round 1 of the 3.0 review found a criterion-only departure for
"keys use 2-4 letters" also explaining an HTTP 500 on that criterion. An equivalence trace is explained by the rule
`equiv-trace:<name>`, which `equiv.py accept` writes.

ADDING ONE AFTER GATE 1. Gate 1 does not hash this file: the registry is append-only from its lock on (05 P2, the
user's decision of 2026-11-09). The lock records each departure present then, ID and a hash of the parsed entry
(record()), and record_problems() names one since removed, edited or duplicated; validate.py and gate-5 fail on
those, and decided() raises so no reader explains a difference meanwhile. Hashing the whole file, as Gate 1 first
did, refused every departure G6 accepted after it. A gate-1 lock whose artifact_hashes still lists the file would
break on an append; that, and a registry whose record is already broken, are the only refusals, and they live in
gate1_allows_append(): change them there.

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
ID = re.compile(r"^D-[0-9]{3,}\Z")
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
    entries = [d for d in data if isinstance(d, dict)]
    # digest() serialises entries with sorted keys; a non-text key (YAML `1: x`) would raise TypeError there.
    odd = [str(d.get("id")) for d in entries if any(not isinstance(k, str) for k in d)]
    if odd:
        raise ValueError(f"departure {', '.join(odd)} has a field name that is not text")
    return entries


def decided(root="."):
    """Every decided entry. Raises while a departure gate-1 recorded is removed or changed: gate_guard does not
    block edits to the registry, so every reader (holdout.py, route.py, gate-5) fails closed here rather than
    letting a widened entry explain a difference."""
    entries = load(root)
    problems = record_problems(root)
    if problems:
        raise ValueError("; ".join(problems))
    return [d for d in entries if _is_decided(d)]


def _is_decided(d):
    return isinstance(d.get("decided_by"), str) and d["decided_by"].strip() != "" and \
        d.get("status", "accepted") != "proposed"


def proposed(root="."):
    return [d for d in load(root) if d.get("status") == "proposed"]


def explained_by(cid, runner=None, pointer=None, value=None, root="."):
    """explains() for a check that must keep running: an unreadable registry explains nothing, and the caller is
    told once on stderr instead of crashing mid-run."""
    try:
        return explains(cid, runner, pointer, value, root)
    except Exception as e:
        global _warned
        if not _warned:
            print(f"warning: {PATH} could not be read ({e}); no difference counts as explained.", file=sys.stderr)
            _warned = True
        return None


_warned = False


def _dropped(cid, root):
    p = os.path.join(root, "docs", "criteria.lock.json")
    try:
        import json
        with open(p, encoding="utf-8") as fh:
            crits = json.load(fh).get("criteria") or []
    except (OSError, ValueError, AttributeError):
        return False
    return any(c.get("id") == cid and c.get("priority") == "Drop" for c in crits if isinstance(c, dict))


def explains(cid, runner, pointer, value, root="."):
    """The id of the decided departure that explains this observed difference on criterion `cid`, or None.
    `runner`, `pointer` and `value` describe what the build did (pointer None when the runner reports no field)."""
    for d in decided(root):
        crits = d.get("criteria") or []
        if crits and cid not in crits:
            continue
        rules = [m for m in d.get("match") or [] if isinstance(m, dict)]
        if not rules:
            if cid in crits and _dropped(cid, root):
                return d["id"]
            continue
        if any(m.get("runner") == runner and m.get("pointer") in (None, pointer) and _rule_ok(str(m.get("rule", "")), value)
               for m in rules):
            return d["id"]
    return None


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


def for_trace(name, root="."):
    """The id of a decided departure accepting this equivalence trace (rule `equiv-trace:<name>`), or None."""
    for d in decided(root):
        for m in d.get("match") or []:
            if isinstance(m, dict) and m.get("rule") == f"equiv-trace:{name}":
                return d["id"]
    return None


def digest(entry):
    """sha256 of one parsed entry: a reflow or CRLF checkout leaves it alone, an edited field does not."""
    import hashlib
    import json
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def record(root="."):
    """{id: digest} for every departure, for gate-1 to write at its lock. Raises ValueError on an unreadable
    registry, an ID that is not C5's D-<nnn> or is repeated, or an undecided entry (proposed, or no or a blank
    decided_by):
    deciding a recorded entry later would read as an edit. The ID pattern also keeps each one a plain YAML key
    that recorded()'s line regex reads back; departures.schema.json holds the same pattern."""
    entries = load(root)
    ids = [str(d.get("id")) for d in entries]
    bad = [i for i in ids if not ID.match(i)]
    if bad:
        raise ValueError(f"{PATH} has departure ID {', '.join(bad)}, not D-<nnn> (contracts C5)")
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"{PATH} repeats the ID {', '.join(dup)}; give each departure its own ID")
    waiting = [i for i, d in zip(ids, entries) if not _is_decided(d)]
    if waiting:
        raise ValueError(f"departure {', '.join(waiting)} is not decided (proposed, or no decided_by): the user "
                         f"decides it before Gate 1 (C5)")
    return {i: digest(d) for i, d in zip(ids, entries)}


def recorded(root="."):
    """{id: digest} from a locked gate-1's `departures_at_lock:`, or {} when gate-1 is not locked."""
    lock = os.path.join(root, "locks", "gate-1.yaml")
    if not os.path.exists(lock):
        return {}
    text = _text(lock)
    if not re.search(r"^status: locked$", text, re.M):
        return {}
    block = re.search(r"^departures_at_lock:\n((?:  .*\n?)*)", text, re.M)
    return dict(re.findall(r"^  (\S+): ([0-9a-f]{64})$", block.group(1), re.M)) if block else {}


def record_problems(root="."):
    """One line per departure gate-1 recorded that is no longer there exactly once and unchanged. An unreadable
    registry is a problem, never an empty one, whether or not gate-1 recorded anything."""
    rec = recorded(root)
    try:
        entries = load(root)
    except Exception as e:
        return [f"{PATH} could not be read ({e}), so the departures gate-1 recorded cannot be checked"]
    out = []
    for did, want in rec.items():
        same = [d for d in entries if str(d.get("id")) == did]
        if not same:
            out.append(f"departure {did} recorded at the gate-1 lock was removed (the registry is append-only)")
        elif len(same) > 1 or digest(same[0]) != want:
            out.append(f"departure {did} recorded at the gate-1 lock was changed (the registry is append-only; "
                       f"add a new departure instead)")
    return out


def gate1_allows_append(root="."):
    """(allowed, why). The one place that decides whether a departure may be added now (see the module doc)."""
    lock = os.path.join(root, "locks", "gate-1.yaml")
    if os.path.exists(lock) and re.search(r"^status: locked$", _text(lock), re.M) and \
            re.search(r"^  docs/departures\.yaml: ", _text(lock), re.M):
        return False, ("gate-1 was locked by a release that hashed docs/departures.yaml, so adding a departure would "
                       "break that lock. Reopen gate-1 with the user (python3 scripts/gate.py reopen gate-1 --reason "
                       "\"...\") and lock it again: the new lock records the departures instead of hashing the file.")
    problems = record_problems(root)
    if problems:
        return False, "; ".join(problems) + ". Restore the registry before adding to it."
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
    write_atomic(p, text.rstrip("\n") + ("\n" if text.strip() else "") + "\n".join(lines) + "\n")
    return did


def write_atomic(p, text):
    """Write `text` to `p` through a temp file renamed over it, so a crash mid-write never leaves the registry
    truncated. holdout.py carries a copy (it runs alone); change both together."""
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = f"{p}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    for d in load():
        state = "PROPOSED" if d.get("status") == "proposed" else ("decided" if d.get("decided_by") else "NO decided_by")
        print(f"{d.get('id')}  {state:9}  {d.get('kind')}  {d.get('summary')}")
