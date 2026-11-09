#!/usr/bin/env python3
"""validate.py — schema-validate all workbench artifacts. Run from the workbench root.

Standard library only: schemas are enforced by schemacheck.py and YAML is read by yamlio.py,
both vendored beside this file (with _vendor/pyyaml/), so a workbench validates with nothing
installed. The plugin's own copy of this file therefore works too, as long as it is run from a
workbench root that has schemas/.

Checks, in order:
  1. plan/progress.yaml against progress.schema.json (+ every id must be one of rspec's features or
     slices), and plan/sequence.yaml against sequence.schema.json (+ it must be a PERMUTATION of
     rspec's slice ids and keep every slice dependency the stories declare)
  2. preflight.json against preflight.schema.json, and plan/autopilot.yaml against
     autopilot.schema.json, if present
  3. sources.yaml `reference.posture`
  4. the scaffold manifest the project's playbook names
  5. locks/gate-*.yaml against lock.schema.json, and locked-gate hash consistency: protected
     files must match recorded hashes

rspec's spec in docs/ is rspec's to check (`rspec:check`); from 3.0.0 nothing here re-checks it.

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

    validators = {"lock": schema("lock.schema.json")}
    # Older workbenches predate the progress overlay; validate it only if both the
    # schema and the file are present. Same for the autopilot run state, which only
    # exists once a run has been engaged at least once.
    # A schema that uses a keyword schemacheck cannot enforce raises SchemaUnsupported here and
    # is deliberately not caught: validating against a schema silently weakened is worse than
    # not validating.
    for name in ("progress", "autopilot", "sequence", "preflight"):
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

    # rspec's feature list and slices (05 P2), read the way every slice report reads them. Their shape,
    # dependency cycles included, is rspec's check_spec.py's to report, not this script's.
    import sequence as seq_lib
    features, slices = seq_lib.plan_features(), seq_lib.plan_slices()

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
    #   - PERMUTATION. An id in the order that no longer exists in docs/build-plan.md, or a slice
    #     added by a gate-2 reopen that never reached the order, is silently a slice that never
    #     runs. parity.py sorts unknown ids last rather than dropping them precisely so this
    #     check is the thing that reports it, not a slice quietly missing from a report.
    #   - DEPENDENCIES. Slice dependencies come from rspec's stories, so an order that violates one
    #     is a contradiction between two artifacts rather than a preference. sequence.py refuses to
    #     write one; this catches a hand-edited file, which is why the file says not to hand-edit it.
    #
    # Absent is normal and always will be: every workbench scaffolded before 0.15.0 has none, and
    # order falls back to docs/build-plan.md's slice order.
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
                problems.append(f"order names slice(s) not in docs/build-plan.md: {', '.join(_js_str(x) for x in unknown)}")
            if absent:
                problems.append(f"slice(s) in docs/build-plan.md missing from the order: {', '.join(_js_str(x) for x in absent)} — "
                                "they would never be scheduled")
            baseline = seq.get("baseline")
            baseline_unknown = [sid for sid in (_as_list(baseline) if _truthy(baseline) else []) if sid not in plan_ids]
            if baseline_unknown:
                problems.append(f"baseline names slice(s) not in docs/build-plan.md: {', '.join(_js_str(x) for x in baseline_unknown)}")
            if problems:
                problems.append("Reconcile with: python3 scripts/sequence.py sync  (bookkeeping after a gate-2 reopen; "
                                "the decision was the reopen, so it needs no reason)")
            else:
                by_id = {s["id"]: s for s in slices}
                v = seq_lib.dependency_violation(order, by_id)
                if v:
                    problems.append(f"order puts {_js_str(v['slice'])} before {_js_str(v['dep'])}, which it depends on "
                                    "through rspec's stories, so this is a contradiction between two artifacts, "
                                    "not a preference — fix the order (python3 scripts/sequence.py reorder).")
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
    # sources.yaml `reference.posture` (05 P3). The P3 guard reads it to decide whether a build lane
    # may read the reference checkout, and it treats an unknown value as the strictest posture; a typo
    # here would otherwise read as a decision nobody made. own-code with a third-party reference is
    # legal for the user to choose (G0 asks), so it warns rather than fails. Line-parsed like
    # playbook.py and hooks/scripts/reference_guard.py read the same block; change them together.
    # ---------------------------------------------------------------------------
    if os.path.exists("sources.yaml"):
        ref_block = re.search(r"^reference:[ \t]*\n((?:(?:[ \t]+.*)?\n)*)", read_text("sources.yaml") + "\n", re.M)

        def ref_field(key):
            f = ref_block and re.search(rf"^[ \t]+{key}:[ \t]*(.*)$", ref_block.group(1), re.M)
            return re.split(r"\s+#", f.group(1))[0].strip().strip("\"'") if f else ""

        posture, kind = ref_field("posture"), ref_field("kind")
        if posture not in ("", "strict", "observe", "own-code"):
            fail("sources.yaml", f"reference.posture is {posture!r}: it must be strict, observe or own-code "
                                 f"(or empty: own-code for kind own-code, else observe)")
        elif posture == "own-code" and kind != "own-code":
            warn("sources.yaml", f"reference.posture is own-code but reference.kind is {kind or 'empty'}: build lanes "
                                 f"may read a reference you do not own. Confirm the licence allows it (G0).")
        else:
            ok(f"sources.yaml (reference.posture: {posture or ('own-code' if kind == 'own-code' else 'observe')})")

    # ---------------------------------------------------------------------------
    # adr/ — the vendored playbook and its scaffold manifest (no ADRs: those are rspec's
    # docs/decisions/). scaffold-repo creates every code repo from that manifest, so a broken one
    # fails here rather than at G5 when the first lane needs a repo. Its absence is normal until
    # `playbook.py vendor` runs before rspec:tech; gate-3 is where it becomes fatal.
    # ---------------------------------------------------------------------------
    import playbook as pb
    res = pb.check_playbook()
    scaffold = res.get("scaffold")
    if res["problems"]:
        fail(pb.VENDORED_PLAYBOOK if not res["disabled"] else pb.SCAFFOLD_LOCAL,
             "\n  ".join(res["problems"]) + f"\n  {pb.PLAYBOOK_REMEDY}")
    elif res["disabled"] and scaffold and scaffold["missing"]:
        ok(f"{pb.SCAFFOLD_LOCAL} (architecture.playbook: none — not written yet)")
    elif res["disabled"] and scaffold and scaffold["problems"]:
        fail(scaffold["path"], "\n  ".join(scaffold["problems"]))
    elif res["missing_vendored"]:
        ok(f'{pb.VENDORED_PLAYBOOK} (not vendored yet — `python3 scripts/playbook.py vendor` copies "{res["selected"]}")')
    elif scaffold:
        ok(f"{scaffold['path']} (scaffold manifest)")

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

    # The departures registry is append-only from the gate-1 lock rather than hashed (05 P2).
    import departures
    for problem in departures.record_problems():
        fail(departures.PATH, problem)

    print(f"\n{failures} failure(s)." if failures else "\nAll artifacts valid.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
