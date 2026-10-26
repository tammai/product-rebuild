#!/usr/bin/env python3
"""validate.py — schema-validate all workbench artifacts. Run from the workbench root.

Standard library only: schemas are enforced by schemacheck.py and YAML is read by yamlio.py,
both vendored beside this file (with _vendor/pyyaml/), so a workbench validates with nothing
installed. The plugin's own copy of this file therefore works too, as long as it is run from a
workbench root that has schemas/.

Checks, in order:
  1. Every findings/**.yaml against finding.schema.json (+ evidence rule, + evidence
     `basis` — where the fact came from, distinct from the miner's `confidence`, +
     a count of findings flagged `signals.instruction_shaped` — advisory, never fatal)
  2. matrix/features.yaml against feature.schema.json
  3. plan/slices.yaml against slice.schema.json (+ acyclic dependencies)
  4. plan/progress.yaml against progress.schema.json (+ ids must exist upstream), and
     plan/sequence.yaml against sequence.schema.json (+ it must be a PERMUTATION of the
     slice ids and must satisfy every gate-2 `depends_on` edge)
  5. contracts/**.yaml structural checks — YAML validity, duplicate keys, and every
     $ref resolving. G5 generates code from these; nothing else in this pipeline
     checked them, so a dangling $ref first surfaced as a codegen failure in a code
     repo, one gate lock too late.
  6. contracts/data-model/*.mermaid — every diagram declares entities; one must exist
     once gate-4 is locked
  7. adr/ against the architecture playbook — every ADR names a concern the vendored
     playbook maps, and cites only sections that map points at
  8. locks/gate-*.yaml against lock.schema.json
  9. Locked-gate hash consistency: protected files must match recorded hashes
 10. plan/autopilot.yaml against autopilot.schema.json, if present

It is a script and not a checklist because every gate lock, the generated CI workflow and the
autopilot loop branch on its exit code: a rule that lives in prose cannot fail a build.

Output and exit code are the contract: `ok`/`warn`/`FAIL` lines, then a summary, exit 1 on any
failure. Warnings go to stderr beside failures, as they did when this was a Node script.

JavaScript behaviours this file reproduces on purpose, because the messages and the order of
the lines depend on them (and the differential tests compare them):
  - `readdirSync(dir, {recursive: true})` walks breadth-first, each directory's entries sorted:
    all of a directory's own entries come before anything inside its subdirectories.
  - Object keys that look like array indices (`200:` under `responses:`) come first, in numeric
    order, before the other keys in insertion order, and a `$ref` pointer matches them as strings.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys

import schemacheck
import yamlio


# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def read_text(p):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


# --- JavaScript value semantics the checks below were written against ----------------------------

def _truthy(v):
    """JS truthiness. `{}` and `[]` are truthy there and falsy in Python, which would silently
    skip a check on an empty-but-present document."""
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v != 0 and v == v
    if isinstance(v, str):
        return v != ""
    return True


def _num_str(v):
    if isinstance(v, float):
        if v != v:
            return "NaN"
        if v in (math.inf, -math.inf):
            return "Infinity" if v > 0 else "-Infinity"
        if v == int(v) and abs(v) < 1e21:
            return str(int(v))
    return str(v)


def _js_str(v):
    """String(v). An absent field arrives as None and reads "undefined", which is what the
    message said when the field was missing; an explicit YAML null is the rare case."""
    if v is None:
        return "undefined"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return _num_str(v)
    if isinstance(v, list):
        return ",".join("" if x is None else _js_str(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


def _key_str(k):
    return "null" if k is None else _js_str(k)


_INDEX_KEY = re.compile(r"(?:0|[1-9][0-9]*)\Z")


def _js_entries(d):
    """Object.entries(d): index-like keys first in numeric order, the rest in insertion order."""
    if not isinstance(d, dict):
        return []
    items = [(_key_str(k), v) for k, v in d.items()]
    idx = sorted((kv for kv in items if _INDEX_KEY.match(kv[0]) and int(kv[0]) < 2 ** 32 - 1),
                 key=lambda kv: int(kv[0]))
    rest = [kv for kv in items if not (_INDEX_KEY.match(kv[0]) and int(kv[0]) < 2 ** 32 - 1)]
    return idx + rest


def _js_keys(d):
    return [k for k, _ in _js_entries(d)]


def _get(obj, key):
    """obj?.key — None for anything that is not a mapping."""
    return obj.get(key) if isinstance(obj, dict) else None


def _as_list(v):
    return v if isinstance(v, list) else []


def _uniq(seq):
    return list(dict.fromkeys(seq))


def _round_half_up(x):
    return math.floor(x + 0.5)


def _list_dir(path):
    # sorted(): Node's readdir is alphabetical (libuv sorts), os.listdir is not.
    return sorted(os.listdir(path))


def _readdir_recursive(base):
    """readdirSync(base, {recursive: true}): breadth-first, paths relative to base."""
    results, queue = [], [base]
    for current in queue:
        for name in _list_dir(current):
            full = os.path.join(current, name)
            results.append(os.path.relpath(full, base))
            if os.path.isdir(full):
                queue.append(full)
    return results


def yaml_files_under(d):
    if not os.path.exists(d):
        return []
    return [p for p in (os.path.join(d, f) for f in _readdir_recursive(d)
                        if f.endswith(".yaml") or f.endswith(".yml")) if os.path.isfile(p)]


RULES_DIR = os.path.join("findings", "rules")


def is_rule_file(f):
    # Both separators: on Windows `join` produces backslashes while the prefix is built with
    # a forward slash. The JS carried the same pair.
    return f.startswith(RULES_DIR + "/") or f.startswith(RULES_DIR + "\\")


def _domain_of(file):
    return re.sub(r"\.ya?ml\Z", "", re.split(r"[/\\]", file)[-1])


# --- RFC 6901 pointers over parsed contracts -------------------------------------------------------

_UNDEFINED = object()


def _js_number(seg):
    """Number(seg) for an array index, or None for NaN."""
    s = seg.strip()
    if s == "":
        return 0
    if re.fullmatch(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", s):
        return float(s)
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", s):
        return int(s, 16)
    if re.fullmatch(r"0[oO][0-7]+", s):
        return int(s, 8)
    if re.fullmatch(r"0[bB][01]+", s):
        return int(s, 2)
    return None


def resolve_pointer(doc, pointer):
    """RFC 6901, plus the two escapes everyone forgets. _UNDEFINED means nothing is there; an
    explicit YAML null IS something, so a pointer ending on one resolves."""
    if pointer == "" or pointer == "/":
        return doc
    node = doc
    for raw in re.sub(r"\A/", "", pointer, count=1).split("/"):
        seg = raw.replace("~1", "/").replace("~0", "~")
        if node is None or not isinstance(node, (dict, list)):
            return _UNDEFINED
        if isinstance(node, list):
            n = _js_number(seg)
            if n is None or n != int(n) or not (0 <= n < len(node)):
                return _UNDEFINED
            node = node[int(n)]
        else:
            node = next((v for k, v in node.items() if _key_str(k) == seg), _UNDEFINED)
        if node is _UNDEFINED:
            return _UNDEFINED
    return node


def walk_refs(node, out, path=""):
    if node is None or not isinstance(node, (dict, list)):
        return out
    if isinstance(node, list):
        for i, v in enumerate(node):
            walk_refs(v, out, f"{path}/{i}")
        return out
    for k, v in _js_entries(node):
        if k == "$ref" and isinstance(v, str):
            out.append((v, path or "/"))
        else:
            walk_refs(v, out, f"{path}/{k}")
    return out


# The checks -------------------------------------------------------------------------------------

def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            # line_buffering so stdout and stderr interleave in order when both go to one pipe
            # (a CI log): block-buffered stdout would print every `ok` after every `FAIL`.
            s.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass

    def schema(n):
        return schemacheck.compile_schema(os.path.join("schemas", n))

    validators = {
        "finding": schema("finding.schema.json"),
        "feature": schema("feature.schema.json"),
        "slice": schema("slice.schema.json"),
        "lock": schema("lock.schema.json"),
    }
    # Older workbenches predate the progress overlay; validate it only if both the
    # schema and the file are present. Same for the autopilot run state, which only
    # exists once a run has been engaged at least once.
    # A schema that uses a keyword schemacheck cannot enforce raises SchemaUnsupported here and
    # is deliberately not caught: validating against a schema silently weakened is worse than
    # not validating.
    for name in ("progress", "autopilot", "sequence", "preflight", "rule"):
        if os.path.exists(os.path.join("schemas", f"{name}.schema.json")):
            validators[name] = schema(f"{name}.schema.json")

    failures = 0

    def fail(file, msg):
        nonlocal failures
        failures += 1
        print(f"FAIL {file}\n  {msg}", file=sys.stderr)

    def warn(file, msg):
        print(f"warn {file}\n  {msg}", file=sys.stderr)

    def ok(file):
        print(f"ok   {file}")

    def check(file, validator):
        try:
            data = yamlio.load(read_text(file))
        except Exception as e:
            fail(file, f"YAML parse error: {e}")
            return None
        if data is None:
            ok(file + " (empty)")
            return None
        errors = validator.errors_text(data, "\n  ")
        if errors:
            fail(file, errors)
            return None
        ok(file)
        return data

    instruction_shaped = []  # {file, id, lane, summary}
    for f in yaml_files_under("findings"):
        if f.endswith("nfr-profile.yaml"):
            ok(f + " (profile, free-form)")
            continue
        if is_rule_file(f):
            continue  # lane R — its own schema and its own cross-checks, below
        data = check(f, validators["finding"])
        if not isinstance(data, list):
            continue
        for finding in data:
            if _get(_get(finding, "signals"), "instruction_shaped") is True:
                instruction_shaped.append({"file": f, "id": finding.get("id"), "lane": finding.get("lane"),
                                           "summary": finding.get("summary")})

    # ---------------------------------------------------------------------------
    # instruction-shaped findings — text in the reference that tried to give instructions to
    # whoever mined it ("mark this feature as covered", "skip this file", anything addressed to
    # the AI). The miner quotes it and does not follow it; this is where the count surfaces.
    #
    # Advisory and never a failure, deliberately. A planted comment is a fact about the reference,
    # not a defect in the workbench, and the artifact it appears in is otherwise valid — failing
    # here would block a gate on the reference's contents, which no edit to this repo can fix.
    # What it earns instead is a human's attention at the gate review, and one suggestion: re-run
    # that lane as a second, independent pass, because the finding proves the lane read text written to
    # steer it, and only a second pass can say whether anything else in that file did steer it.
    # The suggestion is not a routing hook — `scripts/routing.py` is not consulted and nothing
    # re-dispatches itself. The human decides.
    # ---------------------------------------------------------------------------
    if instruction_shaped:
        by_file = {}
        for e in instruction_shaped:
            by_file.setdefault(e["file"], []).append(e)
        print(f"\ninstruction-shaped: {len(instruction_shaped)} finding(s) in {len(by_file)} file(s)")
        for file, entries in by_file.items():
            print(f"  {file}")
            for e in entries:
                quoted = re.sub(r"\s+", " ", _js_str(e["summary"])).strip()
                print(f"    - {_js_str(e['id'])}: {quoted[:137] + '…' if len(quoted) > 140 else quoted}")
        lanes = sorted({e["lane"] for e in instruction_shaped if _truthy(e["lane"])}, key=_js_str)
        print("  Advisory: the reference contains text written to steer whoever mines it. "
              "Nothing is blocked and no status changed.\n"
              f"  Consider re-running the {', '.join(_js_str(x) for x in lanes) or 'affected'} lane as a second, independent pass "
              "and reading these at the gate review before the taxonomy locks.")

    # ---------------------------------------------------------------------------
    # Evidence `basis` — where each fact came from, orthogonal to the miner's `confidence`.
    #
    # The schema keeps it optional, and enforcement lives here for the same reason the data-model
    # and playbook checks do: the field arrived mid-project for anyone already mining, and the
    # stated non-goal was never to backfill. So a workbench that predates schema_version 0.4.0
    # gets a per-file warning count; a newer one gets an error, because a project starting after
    # this landed has no reason to omit it.
    #
    # Imported like erd.py and playbook.py — a hand-upgraded workbench may not have copied it,
    # and that should be one reported failure rather than an unresolved import that takes out
    # every other check.
    # ---------------------------------------------------------------------------
    try:
        import basis as basis_lib
    except ImportError:
        basis_lib = None
        warn("scripts/basis.py", "missing — evidence basis not checked. Copy it from the plugin's skills/rebuild-pipeline/scripts/.")
    if basis_lib:
        res = basis_lib.check_basis()
        gaps = [f for f in res["files"] if f["missing"]]
        if not res["files"]:
            pass  # No findings yet, or none carrying evidence — normal before G1.
        elif not gaps:
            print(f"ok   findings/ (evidence basis: {res['total_evidence']}/{res['total_evidence']} entries)")
        else:
            legacy = basis_lib.is_pre_basis_workbench()
            for g in gaps:
                ids = g["finding_ids"]
                sample = ", ".join(ids[:5]) + (", …" if len(ids) > 5 else "")
                msg = (f"{g['missing']}/{g['evidence']} evidence entr{'y has' if g['missing'] == 1 else 'ies have'} "
                       f"no `basis` ({sample})")
                if legacy:
                    warn(g["file"], msg)
                else:
                    fail(g["file"], msg)
            total = f"{res['total_missing']}/{res['total_evidence']} evidence entries across {len(gaps)} file(s) have no `basis`."
            if legacy:
                warn("findings/", f"{total}\n  {basis_lib.BASIS_REMEDY}\n  Warning only: this workbench predates "
                     'schema_version 0.4.0. After backfilling, set schema_version: "0.4.0" in locks/pipeline.yaml '
                     "to make it enforced. Backfilling old findings is optional — the non-goal was explicit — but "
                     "then leave the version where it is, or every re-validation will fail on history.")
            else:
                print(f"  {total}\n  {basis_lib.BASIS_REMEDY}", file=sys.stderr)

    features = slices = None
    if os.path.exists("matrix/features.yaml"):
        features = check("matrix/features.yaml", validators["feature"])
    if os.path.exists("plan/slices.yaml"):
        slices = check("plan/slices.yaml", validators["slice"])
        if isinstance(slices, list):
            ids = {_get(s, "id") for s in slices}
            visiting, done = set(), set()

            def visit(sid, path):
                if sid in done:
                    return
                if sid in visiting:
                    fail("plan/slices.yaml", f"dependency cycle: {' -> '.join(_js_str(x) for x in [*path, sid])}")
                    return
                visiting.add(sid)
                s = next((x for x in slices if _get(x, "id") == sid), None)
                for d in _as_list(_get(s, "depends_on")):
                    if d not in ids:
                        fail("plan/slices.yaml", f"{_js_str(sid)} depends on unknown slice {_js_str(d)}")
                    else:
                        visit(d, [*path, sid])
                visiting.discard(sid)
                done.add(sid)

            for s in slices:
                visit(_get(s, "id"), [])

    # ---------------------------------------------------------------------------
    # findings/rules/ — lane R's Rule Cards (E5).
    #
    # Schema-validated against rule.schema.json, then two cross-checks the schema cannot
    # express, because both are about agreement BETWEEN artifacts:
    #
    #   - `features[]` against matrix/features.yaml. A card citing F-BILL-014 when the matrix
    #     has no such id is a card no spec will ever find: G5 loads rules by the features in
    #     its slice, so a dangling id makes the rule invisible exactly where it was supposed
    #     to be used. Silent, and it survives a gate lock.
    #   - `entities[]` against findings/ground-truth/reference-erd*.mermaid. Lane R runs after
    #     lane D precisely so it can cite real entities; a name the ERD does not have means the
    #     rule was inferred from a mental model of the reference rather than mined from it.
    #
    # Both are failures, not warnings. They are the checks that make lane R worth having — the
    # alternative is a rules directory that validates perfectly and refers to nothing.
    # ---------------------------------------------------------------------------
    rule_files = [f for f in yaml_files_under("findings") if is_rule_file(f)]
    if rule_files and "rule" not in validators:
        fail(RULES_DIR, "findings/rules/ has files but schemas/rule.schema.json is missing — "
             "Rule Cards are NOT being checked. Copy it from the plugin's skills/rebuild-pipeline/schemas/.")
    elif rule_files:
        all_rules = []  # (file, rule)
        parsed_files = []
        for f in rule_files:
            data = check(f, validators["rule"])
            if not isinstance(data, list):
                continue  # its own schema failure is already reported
            parsed_files.append(f)
            for r in data:
                all_rules.append((f, r))

        # Duplicate ids across files. Per-file uniqueness is not enough: domains are separate
        # files and an id is how a spec's acceptance criterion names a rule, so two cards
        # answering to R-BILL-003 means an AC cites whichever one the reader happens to open.
        seen = {}
        for file, rule in all_rules:
            rid = _get(rule, "id")
            if not _truthy(rid):
                continue
            if rid in seen:
                fail(file, f"duplicate rule id {rid} (also in {seen[rid]})")
            else:
                seen[rid] = file

        feature_ids = {_get(f, "id") for f in features} if isinstance(features, list) else set()
        if feature_ids:
            by_file = {}
            for file, rule in all_rules:
                for fid in _as_list(_get(rule, "features")):
                    if fid in feature_ids:
                        continue
                    by_file.setdefault(file, []).append(
                        f"{_js_str(_get(rule, 'id'))} cites feature {_js_str(fid)}, which matrix/features.yaml does not have")
            for file, problems in by_file.items():
                fail(file, "\n  ".join(problems) + "\n  A rule citing a feature that does not exist is a rule "
                     "G5 will never load — it resolves rules by the features in the slice.")
        elif all_rules:
            warn(RULES_DIR, "matrix/features.yaml is absent or invalid, so rule `features[]` ids were not "
                 "cross-checked. Normal before G2; a problem once the matrix exists.")

        # Entities against the reference ERD. Imported guarded, like every other sibling module.
        try:
            import erd as erd_lib
        except ImportError:
            erd_lib = None  # reported by the data-model pass below
        gt_dir = os.path.join("findings", "ground-truth")
        erd_files = ([os.path.join(gt_dir, f) for f in _list_dir(gt_dir)
                      if re.match(r"reference-erd.*\.mermaid\Z", f)]
                     if os.path.exists(gt_dir) else [])
        if erd_lib and erd_files:
            # Normalised comparison: the ERD writes WORK_PACKAGE and a card may say "work package"
            # or WorkPackage. Neither spelling is wrong and failing on the difference would teach
            # people to copy-paste rather than to cite, so the check is on identity, not on style.
            def norm(e):
                return re.sub(r"[^A-Z0-9]", "", _js_str(e).upper())

            known = set()
            for f in erd_files:
                for e in erd_lib.read_erd(f)["entities"]:
                    known.add(norm(e))
            by_file = {}
            for file, rule in all_rules:
                for ent in _as_list(_get(rule, "entities")):
                    if norm(ent) in known:
                        continue
                    by_file.setdefault(file, []).append(
                        f'{_js_str(_get(rule, "id"))} names entity "{_js_str(ent)}", which no reference-erd*.mermaid declares')
            for file, problems in by_file.items():
                fail(file, "\n  ".join(problems) + f"\n  Checked against: {', '.join(erd_files)}. Lane R runs "
                     "after lane D so it can cite real entities — an unknown name means the rule was inferred "
                     "rather than mined. Fix the card, or mine the entity into the ERD if the reference has it.")
        elif all_rules and not erd_files:
            warn(RULES_DIR, "no findings/ground-truth/reference-erd*.mermaid, so rule `entities[]` were not "
                 "cross-checked. Lane R is supposed to run after lane D has written one.")

        # State machines, assembled from `transition` on state-transition cards. Each card is one
        # edge in prose, so before this an entity's lifecycle was N unrelated cards and the Gate 1
        # rubric's "no state-transition cards for an entity that clearly has a state machine" was
        # found by a judge reading, if at all. One failure, everything else advisory:
        #
        #   - `transition.entity` missing from the card's own `entities[]` FAILS. Two fields on one
        #     card disagreeing is a defect in the card, in the same register as an unknown entity.
        #   - Unreachable states, dead ends and a missing creation edge are REPORTED. A reference can
        #     genuinely carry an orphaned legacy state or a terminal state, and whether the rebuild
        #     keeps it is the gate reviewer's call. Failing here would make such a reference unlockable.
        #
        # Only states some card names are visible: a state the schema has and no card mentions is
        # invisible to this check too. Comparing against lane D's enum values needs a lane D field.
        def norm_ent(e):
            return re.sub(r"[^A-Z0-9]", "", _js_str(e).upper())

        NONE = "(none)"
        machines = {}
        mismatched = {}
        without_transition = 0
        for file, rule in all_rules:
            if _get(rule, "kind") != "state-transition":
                continue
            t = rule.get("transition")
            if not _truthy(t) or not isinstance(t, dict) or not isinstance(t.get("from"), list):
                without_transition += 1
                continue
            if not any(norm_ent(e) == norm_ent(t.get("entity")) for e in _as_list(rule.get("entities"))):
                mismatched.setdefault(file, []).append(
                    f'{_js_str(rule.get("id"))} has transition.entity "{_js_str(t.get("entity"))}", which is not in its entities[]')
            key = f"{norm_ent(t.get('entity'))}.{_js_str(t.get('field'))}"
            if key not in machines:
                machines[key] = {"label": f"{_js_str(t.get('entity'))}.{_js_str(t.get('field'))}", "edges": [], "cards": []}
            m = machines[key]
            for frm in t["from"]:
                m["edges"].append({"from": frm, "to": t.get("to")})
            if rule.get("id") not in m["cards"]:
                m["cards"].append(rule.get("id"))
        for file, problems in mismatched.items():
            fail(file, "\n  ".join(problems) + "\n  The state-machine check files the edge under transition.entity, "
                 "and entities[] is what G5 loads the card by — they have to name the same thing.")
        if machines:
            print("\nstate machines (advisory — read beside Gate 1's D6):")
            for m in machines.values():
                into = _uniq(e["to"] for e in m["edges"])
                out_of = _uniq(e["from"] for e in m["edges"] if e["from"] != NONE)
                states = _uniq([*into, *out_of])
                unreachable = [s for s in out_of if s not in into]
                dead_ends = [s for s in into if s not in out_of]
                created = any(e["from"] == NONE for e in m["edges"])
                print(f"  {m['label']}: {len(states)} state(s), {len(m['edges'])} edge(s) from {len(m['cards'])} card(s)")
                if unreachable:
                    print(f"    unreachable — no card moves into: {', '.join(_js_str(s) for s in unreachable)}")
                if dead_ends:
                    print(f"    dead ends — no card moves out of: {', '.join(_js_str(s) for s in dead_ends)} (confirm they are terminal)")
                if not created:
                    print(f"    no creation edge — no card has from: [{NONE}], so nothing says which state a new record starts in")
        if without_transition:
            print(f"  {without_transition} state-transition card(s) carry no `transition` and are not part of "
                  "the state-machine check. Expected for cards mined before it existed; new lane R runs fill it in.")

        # Judge verification state. Advisory and always will be: `re-derived` is set by
        # rubric-judge, which runs AFTER this validator passes, so a pre-judge run showing every
        # card pending is the normal case and failing on it would make the gate unreachable.
        # What it is for is the gate review — a human reading "12 of 14 re-derived" knows two
        # citations were never opened by anything.
        pending = [(f, r) for f, r in all_rules
                   if (_get(r, "verification") if _truthy(_get(r, "verification")) else "pending") == "pending"]
        total = len(all_rules)
        if total:
            skipped = len(rule_files) - len(parsed_files)
            skipped_note = f", {skipped} file(s) skipped for schema failures above" if skipped else ""
            print(f"ok   {RULES_DIR}/ ({total} rule card(s) in {len(parsed_files)} file(s){skipped_note}; "
                  f"{total - len(pending)}/{total} re-derived by the judge)")

            # Which side of the behavior each domain's cards are on. Error handlers and fallback
            # defaults are the rules a rebuild drops with no test failing, and before `path_kind` a
            # domain with none of them looked exactly like a domain fully mined. Advisory: a domain can
            # genuinely have no error path, but the Gate 1 reviewer should see the zero, not infer it.
            by_domain = {}
            for file, rule in all_rules:
                domain = _domain_of(file)
                d = by_domain.setdefault(domain, {"normal": 0, "error": 0, "default": 0, "invariant": 0})
                pk = _get(rule, "path_kind")
                side = pk if pk in ("error", "default") else "normal"
                d[side] += 1
                if _get(rule, "kind") == "invariant":
                    d["invariant"] += 1
            for domain, d in by_domain.items():
                inv = f"; {d['invariant']} invariant(s)" if d["invariant"] else ""
                no_err = "" if d["error"] else " — no error-path cards; name it in the Gate 1 review if its routes document error responses"
                print(f"  {domain}: {d['normal']} normal, {d['error']} error-path, {d['default']} default{inv}{no_err}")
            if pending:
                ids_shown = ", ".join(_js_str(r.get("id")) for _, r in pending[:12])
                more = ", …" if len(pending) > 12 else ""
                print(f"  {len(pending)} card(s) still `verification: pending` — no agent has opened "
                      f"their citation:\n    {ids_shown}{more}\n  Advisory. rubric-judge sets this at gate time; read it "
                      "beside the gate-1 review, not as a failure.")

    # ---------------------------------------------------------------------------
    # plan/specs/**/*.md — the `rule_id` join between G5's acceptance criteria and lane R.
    #
    # Two different things are reported here and only one of them is a failure:
    #
    #   - A criterion citing a `rule_id` that no Rule Card has is a FAILURE. It is a dangling
    #     reference with the same consequence as a dangling $ref in a contract: it reads as
    #     traceability and traces to nothing.
    #   - Criteria with NO `rule_id`, in a spec whose domains have cards, are COUNTED and
    #     reported as a percentage — never failed. Plenty of criteria legitimately implement no
    #     rule (a response header, a pagination default), so a threshold here would be a number
    #     invented by this script rather than measured. The spec's own target is >= 80% of AC in
    #     rule-bearing slices carrying one; this prints the figure so a human can hold it to that
    #     at the gate review.
    #
    # Specs live in the workbench, not the code repos, for the reason parity/flows/ does: they
    # describe the product. That is also what makes this check possible at all.
    # ---------------------------------------------------------------------------
    spec_files = []
    specs_dir = os.path.join("plan", "specs")
    if os.path.exists(specs_dir):
        spec_files = [p for p in (os.path.join(specs_dir, f) for f in _readdir_recursive(specs_dir)
                                  if f.endswith(".md")) if os.path.isfile(p)]
    if spec_files:
        rule_ids = set()
        domains_with_rules = set()
        invariant_ids = []
        for f in (x for x in yaml_files_under("findings") if is_rule_file(x)):
            try:
                data = yamlio.load(read_text(f))
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            # Domain is the filename (findings/rules/<domain>.yaml) — the same key a spec's
            # `domains:` frontmatter uses, which is what makes "does this spec's domain have rules"
            # answerable without a second index nobody would maintain.
            domain = _domain_of(f)
            for r in data:
                if _truthy(_get(r, "id")):
                    rule_ids.add(r["id"])
                    domains_with_rules.add(domain)
                    if r.get("kind") == "invariant" and r["id"] not in invariant_ids:
                        invariant_ids.append(r["id"])
        cited_ids = set()

        ac_total = ac_with_rule = ac_in_rule_domains = ac_in_rule_domains_with_rule = 0
        for f in spec_files:
            text = read_text(f)
            fm = re.match(r"---\n(.*?)\n---", text, re.S)
            dm_ = re.search(r"^domains:\s*\[?(.*?)\]?\s*$", fm.group(1), re.M) if fm else None
            domains_line = (dm_.group(1) if dm_ else "") or ""
            domains = [d for d in (re.sub(r"^[\"']|[\"']\Z", "", x.strip()) for x in domains_line.split(",")) if d]
            rule_bearing = any(d in domains_with_rules for d in domains)

            # The AC section runs from its heading to the next heading of the same level or EOF. A
            # numbered heading (`## 5. Acceptance criteria`) counts: specs number their sections, and
            # matching only the bare title dropped every criterion of a numbered spec from the figures
            # below with a warning that read as a missing section. Same pattern as lane_plan.py's
            # acceptance_criteria — change both together.
            sec = next((c for c in re.split(r"^##\s+", text, flags=re.M)[1:]
                        if re.match(r"(?:[0-9]+[a-z]?\.\s*)?acceptance criteria\s*\Z", c.split("\n")[0].strip(), re.I)), None)
            if sec is None:
                warn(f, "no `## Acceptance criteria` section — spec-writer's output contract requires one, "
                     "and without it this spec's criteria are not counted in the rule_id figures below.")
                continue
            # [1:] skips the heading line: `5. Acceptance criteria` matches the item pattern, so the Node
            # original counted every numbered-heading spec as one criterion too many, with no rule_id.
            items = [ln for ln in sec.split("\n")[1:] if re.match(r"\s*(?:[0-9]+\.|[-*])\s+\S", ln)]
            problems = []
            for item in items:
                ac_total += 1
                if rule_bearing:
                    ac_in_rule_domains += 1
                cited = re.findall(r"rule_id:\s*(R-[A-Z0-9]+-[0-9]{3})", item)
                if not cited:
                    continue
                ac_with_rule += 1
                if rule_bearing:
                    ac_in_rule_domains_with_rule += 1
                for rid in cited:
                    cited_ids.add(rid)
                    if rid not in rule_ids:
                        problems.append(f"cites rule_id {rid}, which no Rule Card in findings/rules/ defines")
            if problems:
                fail(f, "\n  ".join(problems) + "\n  A criterion citing a card that does not exist reads as "
                     "traceability and traces to nothing. Fix the id, or mine the rule (gate-1 reopen if it is locked).")
            else:
                ok(f)

        if ac_in_rule_domains:
            pct = _round_half_up((ac_in_rule_domains_with_rule / ac_in_rule_domains) * 100)
            without = ac_in_rule_domains - ac_in_rule_domains_with_rule
            print(f"\nrule_id coverage: {ac_in_rule_domains_with_rule}/{ac_in_rule_domains} acceptance criteria "
                  f"({pct}%) in rule-bearing domains cite a rule_id; {without} do not.")
            print("  Advisory — plenty of criteria implement no rule. The target for a slice touching a "
                  "domain with cards is 80%; below that, read it as rules that reached G1 and then went unused.")
        elif ac_total:
            print(f"\nrule_id coverage: not applicable — {ac_total} acceptance criteria, none in a domain "
                  "that has Rule Cards.")

        # An invariant has no trigger, so no single module "owns" it: every module that writes its
        # entities must test it (g5-build.md). One that no criterion cites anywhere is a property
        # nothing in the build checks. Advisory, because before the first slice that writes the
        # entity, being uncited is the expected state.
        uncited_invariants = [i for i in invariant_ids if i not in cited_ids]
        if uncited_invariants:
            print(f"\ninvariants no acceptance criterion cites yet ({len(uncited_invariants)}): "
                  f"{', '.join(uncited_invariants)}\n  Advisory — expected until a slice writes their entities; "
                  "after that, every spec for a module that writes one should cite it.")

    # The mutable progress overlay. A typo'd id here would silently never match a
    # feature, so every key must resolve against the locked artifacts.
    if "progress" in validators and os.path.exists("plan/progress.yaml"):
        progress = check("plan/progress.yaml", validators["progress"])
        if isinstance(progress, (dict, list)):
            def known(arr):
                return {_get(x, "id") for x in arr} if isinstance(arr, list) else set()

            feature_ids, slice_ids = known(features), known(slices)

            def section_of(section):
                v = _get(progress, section)
                return v if _truthy(v) else {}

            def cross_ref(section, ids, label):
                if not ids:
                    return  # upstream artifact absent or invalid — already reported
                for pid in _js_keys(section_of(section)):
                    if pid not in ids:
                        fail("plan/progress.yaml", f"{section}: unknown {label} {pid}")

            cross_ref("features", feature_ids, "feature")
            cross_ref("feature_notes", feature_ids, "feature")
            cross_ref("slices", slice_ids, "slice")
            cross_ref("notes", slice_ids, "slice")
            # A descoped feature leaves the coverage denominator in parity.py and slice_review.py, so
            # one with no recorded reason is a feature that vanished from every figure unexplained.
            notes = _get(progress, "feature_notes")

            def note_of(pid):
                v = next((val for k, val in _js_entries(notes) if k == pid), None) if isinstance(notes, dict) else None
                return _js_str(v if _truthy(v) else "").strip()

            unexplained = [pid for pid, st in _js_entries(section_of("features"))
                           if st == "descoped" and not note_of(pid)]
            if unexplained:
                fail("plan/progress.yaml", f"descoped with no reason under feature_notes: {', '.join(unexplained)}\n"
                     "  Descoping drops a feature from every coverage figure; the reason is what keeps that "
                     f'visible. Add one line per feature, e.g. feature_notes: {{ {unexplained[0]}: "ruled out by <who>, <date>: <why>" }}')

    # ---------------------------------------------------------------------------
    # plan/sequence.yaml — the slice execution order.
    #
    # gate-2 locks slice BOUNDARIES; the ORDER lives here so that revising it is a logged decision
    # rather than a formal reopen (see scripts/sequence.py). Two checks earn their keep, and
    # neither is expressible in the schema:
    #
    #   - PERMUTATION. An id in the order that no longer exists in plan/slices.yaml, or a slice
    #     added by a gate-2 reopen that never reached the order, is silently a slice that never
    #     runs. parity.py sorts unknown ids last rather than dropping them precisely so this
    #     check is the thing that reports it, not a slice quietly missing from a report.
    #   - DEPENDENCIES. `depends_on` is gate-2 locked, so an order that violates it is a
    #     contradiction between two artifacts rather than a preference. sequence.py refuses to
    #     write one; this catches a hand-edited file, which is why the file says not to hand-edit it.
    #
    # Absent is normal and always will be: every workbench scaffolded before 0.15.0 has none, and
    # order falls back to plan/slices.yaml's array exactly as it did before.
    # ---------------------------------------------------------------------------
    if "sequence" in validators and os.path.exists("plan/sequence.yaml"):
        seq = check("plan/sequence.yaml", validators["sequence"])
        if isinstance(seq, dict) and isinstance(seq.get("order"), list) and isinstance(slices, list):
            order = seq["order"]
            plan_ids = [i for i in (_get(s, "id") for s in slices) if _truthy(i)]
            problems = []
            dupes = [sid for i, sid in enumerate(order) if order.index(sid) != i]
            if dupes:
                problems.append(f"order lists {', '.join(_js_str(x) for x in _uniq(dupes))} more than once")
            unknown = [sid for sid in order if sid not in plan_ids]
            absent = [sid for sid in plan_ids if sid not in order]
            if unknown:
                problems.append(f"order names slice(s) not in plan/slices.yaml: {', '.join(_js_str(x) for x in unknown)}")
            if absent:
                problems.append(f"slice(s) in plan/slices.yaml missing from the order: {', '.join(_js_str(x) for x in absent)} — "
                                "they would never be scheduled")
            baseline = seq.get("baseline")
            baseline_unknown = [sid for sid in (_as_list(baseline) if _truthy(baseline) else []) if sid not in plan_ids]
            if baseline_unknown:
                problems.append(f"baseline names slice(s) not in plan/slices.yaml: {', '.join(_js_str(x) for x in baseline_unknown)}")
            if problems:
                problems.append("Reconcile with: python3 scripts/sequence.py sync  (bookkeeping after a gate-2 reopen; "
                                "the decision was the reopen, so it needs no reason)")
            else:
                # Imported guarded, like erd.py and playbook.py, so one missing script is a reported gap
                # rather than an unresolved import that takes out every other check.
                try:
                    import sequence as seq_lib
                except ImportError:
                    seq_lib = None
                    warn("scripts/sequence.py", "missing — slice order not checked against depends_on. Copy it from the plugin's skills/rebuild-pipeline/scripts/.")
                if seq_lib:
                    by_id = {s["id"]: s for s in slices if _truthy(_get(s, "id"))}
                    v = seq_lib.dependency_violation(order, by_id)
                    if v:
                        problems.append(f"order puts {_js_str(v['slice'])} before {_js_str(v['dep'])}, which it depends on. "
                                        "`depends_on` is gate-2 locked, so this is a contradiction between two artifacts, "
                                        "not a preference — fix the order (python3 scripts/sequence.py reorder) or reopen gate-2.")
            if problems:
                fail("plan/sequence.yaml", "\n  ".join(problems))

    # The G0 preflight result. Absent is normal and stays normal: every workbench scaffolded
    # before 0.16.0 has none, and a project mid-G3 has no reason to go back and make one. What
    # is checked is that a preflight.json which DOES exist is one autopilot.py and SKILL.md's
    # phase detection can read — both branch on `verdict` and `lanes`, and a hand-edited file
    # that lost either would make them fall through to "no preflight" silently, which is the
    # one reading that is worse than either verdict.
    if "preflight" in validators and os.path.exists("preflight.json"):
        pf = None
        try:
            with open("preflight.json", "r", encoding="utf-8", errors="replace") as fh:
                pf = json.load(fh)
        except Exception as e:
            fail("preflight.json", f"JSON parse error: {e}")
        if _truthy(pf):
            errors = validators["preflight"].errors_text(pf, "\n  ")
            if errors:
                fail("preflight.json", errors + "\n  Do not hand-edit it — re-run `python3 scripts/preflight.py`.")
            else:
                lanes = " ".join(f"{k}:{_js_str(v)}" for k, v in _js_entries(pf["lanes"]))
                ok(f"preflight.json ({_js_str(pf.get('verdict'))} — lanes {lanes})")

    # Autopilot run state. Nothing downstream reads it — it is a breadcrumb for whoever picks
    # the session back up — but a malformed one means autopilot.py is round-tripping badly,
    # and the file it is round-tripping records what an unattended run did.
    if "autopilot" in validators and os.path.exists("plan/autopilot.yaml"):
        check("plan/autopilot.yaml", validators["autopilot"])

    # ---------------------------------------------------------------------------
    # contracts/ — the artifacts G5 generates code from.
    #
    # Deliberately NOT a full OpenAPI/AsyncAPI spec validator: that needs a real
    # dependency, and the plugin ships none. What it does check is the class of
    # defect that actually costs a slice — a $ref pointing at nothing. That is
    # invisible to a YAML parse, invisible to review, and shows up as a codegen
    # error in a code repo after the gate is locked and the tag is pinned.
    # ---------------------------------------------------------------------------
    contract_docs = {}  # path -> parsed doc, so cross-file refs parse once

    def load_contract(file):
        if file in contract_docs:
            return contract_docs[file]
        doc = None
        try:
            doc = yamlio.load(read_text(file))
        except Exception:
            pass  # reported by its own pass
        contract_docs[file] = doc
        return doc

    for file in yaml_files_under("contracts"):
        # yamlio raises on a duplicate key, where a plain parse silently resolves last-wins.
        # Two operations sharing a path key, or a schema defined twice, is exactly the merge
        # accident this catches.
        try:
            doc = yamlio.load(read_text(file))
        except Exception as e:
            fail(file, str(e))
            continue
        if doc is None or not isinstance(doc, (dict, list)):
            ok(file + " (empty)")
            continue
        contract_docs[file] = doc

        problems = []
        for ref, at in walk_refs(doc, []):
            parts = ref.split("#")
            target = parts[0]
            pointer = parts[1] if len(parts) > 1 else ""
            if ref.startswith("http://") or ref.startswith("https://"):
                continue  # remote: not ours to resolve
            if target == "":
                if resolve_pointer(doc, pointer) is _UNDEFINED:
                    problems.append(f"dangling $ref at {at}: {ref}")
                continue
            other = os.path.abspath(os.path.join(os.path.dirname(file), target))
            if not os.path.exists(other):
                problems.append(f"$ref at {at} points at a missing file: {ref}")
                continue
            other_doc = load_contract(other)
            if other_doc is None:
                problems.append(f"$ref at {at} targets an unparseable file: {ref}")
                continue
            if pointer and resolve_pointer(other_doc, pointer) is _UNDEFINED:
                problems.append(f"dangling cross-file $ref at {at}: {ref}")

        # Kind-specific checks, only where the document declares its kind. A contract
        # file that is neither (the data-model prose files are .md, but be tolerant)
        # still gets the YAML + $ref pass above, which is the valuable part.
        openapi, asyncapi = _get(doc, "openapi"), _get(doc, "asyncapi")
        if isinstance(openapi, str):
            if not re.match(r"3\.", openapi):
                problems.append(f"unexpected OpenAPI version: {openapi}")
            declared = set(_js_keys(_get(_get(doc, "components"), "securitySchemes") or {}))
            seen_op_ids = {}
            for p, item in _js_entries(_get(doc, "paths") or {}):
                if item is None or not isinstance(item, (dict, list)):
                    continue
                for m in ("get", "put", "post", "delete", "patch", "options", "head", "trace"):
                    op = _get(item, m)
                    if not _truthy(op) or not isinstance(op, (dict, list)):
                        continue
                    where = f"{m.upper()} {p}"
                    op_id = _get(op, "operationId")
                    if not _truthy(op_id):
                        problems.append(f"{where}: missing operationId")
                    elif op_id in seen_op_ids:
                        problems.append(f'duplicate operationId "{op_id}" ({seen_op_ids[op_id]} and {where})')
                    else:
                        seen_op_ids[op_id] = where
                    responses = _get(op, "responses")
                    if not _truthy(responses) or not len(_js_keys(responses) if isinstance(responses, dict) else responses):
                        problems.append(f"{where}: no responses declared")
                    for req in [*_as_list(_get(op, "security")), *_as_list(_get(doc, "security"))]:
                        for name in _js_keys(req if _truthy(req) else {}):
                            if name not in declared:
                                problems.append(f'{where}: security scheme "{name}" is not in components.securitySchemes')
        elif isinstance(asyncapi, str):
            if not _js_keys(_get(doc, "channels") or {}):
                problems.append("asyncapi document declares no channels")

        if problems:
            fail(file, "\n  ".join(problems))
        else:
            ok(file)

    # ---------------------------------------------------------------------------
    # contracts/data-model/ — the artifact G4b drafts BEFORE the three contract layers.
    #
    # Existence is required only once gate-4 is locked: before that there is legitimately
    # nothing here, and this script runs after every mining batch. The check that actually
    # prevents a bad lock lives in gate.py, which refuses to lock gate-4 without a data
    # model — by the time a locked gate-4 fails here, the tag is already cut.
    #
    # Entities, not just an `erDiagram` header: a stub satisfies the header forever.
    # ---------------------------------------------------------------------------
    # Imported here rather than at the top so a hand-upgraded workbench that copied this file
    # without erd.py still runs every other check and reports the gap as one failure, instead
    # of dying on an unresolved import before the first artifact is read.
    try:
        import erd
    except ImportError:
        erd = None
        fail("scripts/erd.py", "missing — data model not checked. Copy it from the plugin's skills/rebuild-pipeline/scripts/.")
    if erd:
        gate4 = os.path.join("locks", "gate-4.yaml")
        gate4_locked = os.path.exists(gate4) and re.search(r"^status: locked$", read_text(gate4), re.M) is not None
        dm = erd.check_data_model()
        issues = list(dm["problems"])
        if dm["missing"] and gate4_locked:
            issues.append("no .mermaid file, but gate-4 is locked")
        if issues:
            body = "\n  ".join(issues) + f"\n  {erd.DATA_MODEL_REMEDY}"
            if erd.is_legacy_workbench():
                warn(erd.DATA_MODEL_DIR, f"{body}\n  Warning only: this workbench predates schema_version 0.2.0. "
                     'After adding the data model, set schema_version: "0.2.0" in locks/pipeline.yaml to make it enforced.')
            else:
                fail(erd.DATA_MODEL_DIR, body)
        else:
            for f in dm["files"]:
                ok(f)

    # ---------------------------------------------------------------------------
    # adr/ against the architecture playbook.
    #
    # G4a is playbook-driven: `sources.yaml` names a playbook, G4a vendors it to
    # `adr/playbook.md`, and its `concerns:` map is the list of ADRs the phase owes. Three
    # things are checkable and none of them were before 0.11.0:
    #   - the vendored copy exists and parses (without it, "cites §7" names nothing)
    #   - every ADR declares which concern it decides, and it is a concern the map has
    #   - every `§` an ADR cites is a section that map actually points at
    # The last one is the check that makes a swapped playbook safe. It cannot catch a
    # plausible-looking wrong section — §8 means storage in one playbook and auth in another —
    # only one the map never names at all. That is why the vendored copy is hashed into Gate 3:
    # the check narrows the window, the hash closes it.
    #
    # Imported like erd.py, for the same reason: a hand-upgraded workbench may not have copied
    # it, and that should be one reported failure rather than an unresolved import that takes
    # out every other check.
    # ---------------------------------------------------------------------------
    try:
        import playbook as pb
    except ImportError:
        pb = None
        fail("scripts/playbook.py", "missing — architecture playbook not checked. Copy it from the plugin's skills/rebuild-pipeline/scripts/.")
    if pb:
        VENDORED_PLAYBOOK = pb.VENDORED_PLAYBOOK
        res = pb.check_playbook()
        scaffold = res.get("scaffold")
        if res["disabled"]:
            ok(f"{VENDORED_PLAYBOOK} (architecture.playbook: none — G4a runs blank-slate, no playbook to check)")
            # The project's own manifest is checked once it exists; its absence is normal until G4a.
            if scaffold and not scaffold["missing"] and scaffold["problems"]:
                fail(scaffold["path"], "\n  ".join(scaffold["problems"]))
            elif scaffold and not scaffold["missing"]:
                ok(f"{scaffold['path']} (scaffold manifest)")
        else:
            # A missing vendored copy is normal until G4a runs, which is most of a project's life —
            # failing on it from G1 onward would make `python3 scripts/validate.py` red for weeks and
            # teach everyone to ignore it. It becomes fatal once gate-3 is locked, because then the
            # ADRs cite a file that is supposed to be hashed into that lock. Refusing to lock WITHOUT
            # it is gate.py's job, for the same reason the data-model check lives there: gate status
            # is open|locked with nothing between, so a validator firing on `locked` is one tag too late.
            gate3 = os.path.join("locks", "gate-3.yaml")
            gate3_locked = os.path.exists(gate3) and re.search(r"^status: locked$", read_text(gate3), re.M) is not None
            issues = list(res["problems"])
            if res["missing_vendored"] and gate3_locked:
                issues.append(f"gate-3 is locked but {VENDORED_PLAYBOOK} does not exist — the ADRs cite a playbook nothing pins")
            meta = res.get("meta")
            if issues:
                body = "\n  ".join(issues) + f"\n  {pb.PLAYBOOK_REMEDY}"
                if pb.is_pre_playbook_workbench():
                    warn(VENDORED_PLAYBOOK, f"{body}\n  Warning only: this workbench predates schema_version 0.3.0. "
                         'After backfilling, set schema_version: "0.3.0" in locks/pipeline.yaml to make it enforced.')
                else:
                    fail(VENDORED_PLAYBOOK, body)
            elif res["missing_vendored"]:
                by_default = ", the org default, since sources.yaml names none" if res["selected_by"] == "default" else ""
                ok(f'{VENDORED_PLAYBOOK} (not vendored yet — G4a copies the "{res["selected"]}" playbook here{by_default})')
            else:
                ok(f"{VENDORED_PLAYBOOK} ({_js_str(_get(meta, 'playbook'))} via {res['selected_by']}, "
                   f"{len(_get(meta, 'concerns') or {})} concerns, {len(res['adrs'])} ADR(s), "
                   f"{len(res['undecided'])} concern(s) still undecided)")

    for f in (x for x in yaml_files_under("locks") if re.search(r"gate-[0-9]\.yaml\Z", x)):
        lock = check(f, validators["lock"])
        if _get(lock, "status") == "locked" and _truthy(lock.get("artifact_hashes")):
            for file, expected in _js_entries(lock["artifact_hashes"]):
                if not os.path.exists(file):
                    fail(f, f"locked file missing: {file}")
                    continue
                with open(file, "rb") as fh:
                    now = hashlib.sha256(fh.read()).hexdigest()
                if now != expected:
                    fail(f, f"locked artifact modified: {file} (reopen {_js_str(lock.get('gate'))} instead of editing)")

    print(f"\n{failures} failure(s)." if failures else "\nAll artifacts valid.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
