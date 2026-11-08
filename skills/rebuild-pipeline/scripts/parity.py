#!/usr/bin/env python3
"""parity.py — G6 coverage report (05 P6 step 4). Run from the workbench root.
Counts rspec's features (docs/features.md) by this rebuild's progress, lists rspec's slices
(docs/build-plan.md), and writes parity/<date>.md, with — when the AC suite left a JUnit file at
parity/<date>-ac.xml — the AC pass rate that suite actually produced.

Progress lives in plan/progress.yaml, NOT in the gate-locked artifacts. features.md (gate-1) and
build-plan.md (gate-2) are hashed whole, so recording progress there would mean a formal gate
reopen for bookkeeping, and a moved hash for every submodule pin, once per slice. Gates protect
decisions; progress is not a decision. A feature with no progress entry is `planned`, a Drop is
`descoped` (its departure is the recorded ruling), a slice with none is `pending`.

It is a script rather than a line in a doc because the report is regenerated every slice
boundary and must be computed from the files, not remembered (see the AC section below).

PORTING NOTES (Node original: parity.mjs). The report is a committed, human-read artifact, so
its text is reproduced exactly, including how JS prints a missing field: `${f.name}` with no
`name:` is the word `undefined`, and a `null` is the word `null` (`js_str`). Where JS sorts an
array of [key, object] pairs with no comparator, it sorts the strings "key,[object Object]"
(see `_pair_sort_key`); that is kept because it decides row order. The AC and equivalence
sections each import their library guarded, as the original did, so a hand-upgraded
workbench missing one loses that section with a warning rather than the whole report. The helpers
below are copied from acsuite.py rather than imported for the same reason: the
import is allowed to fail and the report must still render.
"""

import math
import os
import re
import sys
from datetime import datetime

import sequence
import yamlio

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def _read_text(p):
    with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


# --- JS semantics the report text depends on (copied from acsuite.py / equiv.py; change together) ---
_JS_WS = " \t\n\v\f\r           " \
         "      　﻿"
_WS = "[" + _JS_WS + "]"


class _Undefined:
    def __repr__(self):
        return "undefined"


UNDEF = _Undefined()


def _num_str(x):
    if isinstance(x, int):
        if abs(x) < 2 ** 53:
            return str(x)
        x = float(x)
    if x != x:
        return "NaN"
    if x in (float("inf"), float("-inf")):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    mant, _, ex = repr(abs(x)).partition("e")
    exp = int(ex) if ex else 0
    ip, _, fp = mant.partition(".")
    digits, n = ip + fp, len(ip) + exp
    while digits.startswith("0") and len(digits) > 1:
        digits, n = digits[1:], n - 1
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        es = ("+" if e >= 0 else "-") + str(abs(e))
        body = digits + "e" + es if k == 1 else digits[0] + "." + digits[1:] + "e" + es
    return sign + body


def js_str(x):
    """String(x) / a template-literal interpolation."""
    if x is UNDEF:
        return "undefined"
    if x is None:
        return "null"
    if x is True:
        return "true"
    if x is False:
        return "false"
    if isinstance(x, (int, float)):
        return _num_str(x)
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return ",".join("" if e is None or e is UNDEF else js_str(e) for e in x)
    return "[object Object]"


def truthy(x):
    if x is UNDEF or x is None or x is False or x == "":
        return False
    if isinstance(x, (int, float)) and not isinstance(x, bool) and (x == 0 or x != x):
        return False
    return True


def js_trim(s):
    return s.strip(_JS_WS)


def js_round(x):
    """Math.round: halves go up. Python's round() goes to even, which would print 12 for 12.5%."""
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


def _u16(s):
    return s.encode("utf-16-be", "surrogatepass")


def _pair_sort_key(key):
    """`[...map.entries()].sort()` with no comparator compares String([key, object]), i.e.
    "key,[object Object]". It matters only when one key is a prefix of another followed by a
    character that sorts below ','."""
    return _u16(key + ",[object Object]")


def _get(o, k):
    """`o.k`: undefined when missing, and not an error when o is not an object."""
    return o.get(k, UNDEF) if isinstance(o, dict) else UNDEF


def _lookup(d, k):
    """`d[k]` where k came from a YAML field: JS object keys are strings, so 3 and "3" are one key."""
    if not isinstance(d, dict):
        return UNDEF
    try:
        if k in d:
            return d[k]
    except TypeError:
        pass
    ks = js_str(k)
    for dk, v in d.items():
        if js_str(dk) == ks:
            return v
    return UNDEF


def _key(x):
    """A hashable stand-in for SameValueZero, for a Set of YAML scalars."""
    try:
        hash(x)
        return (type(x).__name__ if not isinstance(x, (int, float)) or isinstance(x, bool) else "number", x)
    except TypeError:
        return ("id", id(x))


def _nonnull(v, fallback):
    return fallback if v is None else v


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    def warn(msg):
        print(msg, file=sys.stderr)

    # Design rule 6: a report that cannot read rspec's list says so and fails, rather than
    # writing a 0% coverage report boundary.py would relay as step 4's result.
    if not os.path.exists(sequence.FEATURES):
        warn(f"not run: no {sequence.FEATURES} here (rspec:features writes it; run from the workbench root).")
        return 1
    parse = yamlio.load

    def read_yaml(p, fallback):
        return _nonnull(parse(_read_text(p)), fallback) if os.path.exists(p) else fallback

    def orv(*vals):
        """`a || b || c`: the first truthy value, else the last."""
        for v in vals[:-1]:
            if truthy(v):
                return v
        return vals[-1]

    progress = orv(read_yaml("plan/progress.yaml", {}), {})
    feature_progress = orv(_get(progress, "features"), {})
    slice_progress = orv(_get(progress, "slices"), {})
    notes = orv(_get(progress, "notes"), {})
    feature_notes = orv(_get(progress, "feature_notes"), {})

    def with_status(item, prog, fallback):
        base = dict(item) if isinstance(item, dict) else {}
        base["status"] = orv(_lookup(prog, _get(item, "id")), _get(item, "status"), fallback)
        return base

    features = [with_status(f, feature_progress, "descoped" if f["priority"] == "Drop" else "planned")
                for f in sequence.plan_features()]
    slices = [with_status(s, slice_progress, "pending") for s in sequence.plan_slices()]

    # Slice ORDER lives in plan/sequence.yaml, not in build-plan.md, which gate-2 hashes whole (see
    # sequence.py's header). Reading it keeps "Slice progress" in the order actually being executed.
    seq = sequence.read_sequence()
    if seq["present"]:
        rank = {}
        for i, sid in enumerate(seq["order"]):
            rank[_key(sid)] = i
        # Anything absent from the overlay sorts last rather than vanishing: silently dropping a
        # slice from the report is the one behaviour that would hide a non-permutation. (Stable,
        # like Array.prototype.sort; the JS comparator's Infinity - Infinity is NaN, which sorts as
        # "equal".)
        slices = sorted(slices, key=lambda s: rank.get(_key(_get(s, "id")), float("inf")))

    def by(st):
        return [f for f in features if f["status"] == st]

    buckets = {
        "covered": by("covered"), "partial": by("partial"),
        "missing": by("missing"), "planned": by("planned"),
        "upstream": by("upstream-candidate"),
        "descoped": by("descoped"),
    }
    # `deployed` counts too: a slice that shipped should have its features recorded,
    # even when a done_means clause is knowingly unmet and it never reaches `done`.
    shipped = ("done", "deployed")
    # flatMap: an array contributes its elements, anything else (including a missing `features:`,
    # which is `undefined`) contributes itself — so a shipped slice with no `features:` list shows
    # up as one unrecorded entry below, exactly as it did in the Node report.
    done_slice_features = {}
    for s in slices:
        if s["status"] in shipped:
            f = _get(s, "features")
            for e in (f if isinstance(f, list) else [f]):
                done_slice_features.setdefault(_key(e), e)
    suspicious = [f for f in features if _key(_get(f, "id")) in done_slice_features and f["status"] == "planned"]
    if not os.path.exists("plan/progress.yaml"):
        warn("note: no plan/progress.yaml — every feature reads as planned and every slice as pending.")

    # The LOCAL date, like every dated file in parity/ — see local_date() in acsuite.py. acsuite is
    # imported guarded further down, so the same lines are inlined here rather than borrowed:
    # falling back to the UTC date when it is missing would bring back the bug it fixed.
    _d = datetime.now()
    date = f"{_d.year}-{_d.month:02d}-{_d.day:02d}"
    # A descoped feature is a recorded ruling not to build it, so it leaves the denominator: counting
    # it as uncovered would make the figure unreachable by design. It stays visible in its own
    # section with its reason (validate.py refuses one without), and in the headline count.
    in_scope = len(features) - len(buckets["descoped"])
    pct = js_round((len(buckets["covered"]) / in_scope) * 100) if in_scope else 0

    def list_md(arr):
        if not arr:
            return "- none"
        out = []
        for f in arr:
            note = _lookup(feature_notes, _get(f, "id"))
            out.append(f"- {js_str(_get(f, 'id'))} {js_str(_get(f, 'name'))}"
                       + (f" — {js_trim(note)}" if truthy(note) else ""))
        return "\n".join(out)

    # ---------------------------------------------------------------------------
    # AC pass rate, from the AC suite's own JUnit output — not from a hand-written summary.
    #
    # g6-parity.md step 1 runs `maestro test parity/flows --format junit --output
    # parity/<date>-ac.xml`. Reading that file here rather than asking a human to transcribe the
    # result is the same rule g5-build.md states for verification scripts: an artifact a human
    # reads afterwards must name only what actually ran. A transcribed pass rate is exactly the
    # banner that survives after the run that produced it is forgotten.
    #
    # The parsing itself lives in acsuite.py (shared with slice_review.py, which needs a richer
    # read of the same file) — including why it is not a real XML parser, and why anything it cannot
    # read is reported as unreadable rather than counted as zero failures.
    #
    # This report reads TODAY's file only, never the newest on disk: it is dated, and borrowing
    # another day's numbers would put a pass rate under a heading that did not produce it.
    # ---------------------------------------------------------------------------
    AC_JUNIT = f"parity/{date}-ac.xml"
    # The reader itself lives in acsuite.py, shared with slice_review.py. Imported guarded: a
    # hand-upgraded workbench that copied this file without it loses
    # the AC section with a warning rather than dying on an unresolved import. Losing the section
    # is safe here precisely because AC_TITLE then stays out of OWNED below, so a previously
    # generated one is preserved instead of erased.
    try:
        ac_lib = __import__("acsuite")
    except ImportError:
        ac_lib = None
        warn("note: scripts/acsuite.py is missing — no AC pass rate in this report. "
             "Copy it from the plugin's skills/rebuild-pipeline/scripts/. Do not read its absence as a pass.")
    ac = ac_lib.read_ac_suite(AC_JUNIT) if ac_lib else None
    # The rerun of the joint run's failures, counted by the same function slice_review.py uses, so
    # the two reports cannot disagree on a pass rate. Absent in a workbench whose acsuite predates it.
    AC_RERUN = f"parity/{date}-ac-rerun.xml"
    counted = None
    if ac and not ac.get("unreadable") and hasattr(ac_lib, "count_with_rerun"):
        counted = ac_lib.count_with_rerun(
            ac, ac_lib.read_ac_suite(AC_RERUN),
            ac_lib.read_run_meta(ac_lib.run_meta_path(date)),
            ac_lib.read_run_meta(ac_lib.run_meta_path(date, {"rerun": True})))
    # The section is owned only when there is a JUnit file to own it from. Without one, the title
    # stays out of OWNED so a previously generated section — or a hand-written `## AC suite` for a
    # project whose AC suite is not Maestro — is preserved by the merge below instead of erased.
    AC_TITLE = "AC suite (Maestro JUnit)"
    ac_section = ""
    if ac and ac.get("unreadable"):
        ac_section = (f"\n## {AC_TITLE}\n\n- `{AC_JUNIT}` exists but could not be read as JUnit "
                      f"({ac['unreadable']}). Pass rate NOT reported — do not read its absence as a pass.\n")
        warn(f"warning: {AC_JUNIT} is not readable as JUnit ({ac['unreadable']}) — no AC pass rate in the report.")
    elif counted:
        desc = ac_lib.describe_counted(counted, AC_JUNIT)
        headline, lines, not_green = desc["headline"], desc["lines"], desc["notGreen"]
        if not_green:
            warn(f"warning: {AC_JUNIT} is NOT GREEN — too many skips, or skips for an unset environment variable. See the report.")
        failed = "\n\nFailed:\n" + "\n".join(f"- {n}" for n in counted["stillFailing"]) if counted["stillFailing"] else ""
        skipped = " A skipped AC is not a passing one." if counted["skipped"] else ""
        ac_section = (f"\n## {AC_TITLE}\n\nAC pass rate: {headline}.{skipped} Source: `{AC_JUNIT}`"
                      + (f" and `{AC_RERUN}`" if counted["rerun"] else "")
                      + "." + ("\n\n" + "\n".join(lines) if lines else "") + failed + "\n")
    elif ac:
        rate = js_round((ac["passed"] / ac["total"]) * 100) if ac["total"] else 0
        failed = "\n\nFailed:\n" + "\n".join(f"- {c['name']}" for c in ac["failures"]) if ac["failures"] else ""
        skipped = f" {ac['skipped']} skipped — a skipped AC is not a passing one." if ac["skipped"] else ""
        ac_section = (f"\n## {AC_TITLE}\n\nAC pass rate: {ac['passed']}/{ac['total']} ({rate}%), "
                      f"{ac['failed']} failed.{skipped} Source: `{AC_JUNIT}`.{failed}\n")

    # ---------------------------------------------------------------------------
    # Equivalence (lane E8) — does the rebuild produce what the OLD system produced?
    #
    # The AC suite asks whether the rebuild does what the spec says. Coverage asks how much of the
    # reference exists. Neither asks whether `POST /invoices` returns the same totals the old system
    # returned, and for a rebuild of your own legacy system that is the question the project is
    # actually about.
    #
    # THREE NUMBERS, NOT ONE. Recorded, replayed, green. A trace that exists and was never replayed
    # is not a pass and not a failure — it is evidence nobody checked, and it is invisible in the
    # JUnit because the JUnit contains only what ran. Reporting "6/6 green" over a directory holding
    # eight traces is the exact overclaim this section exists to prevent.
    #
    # WHEN THE LANE DOES NOT APPLY, SAY SO. Under posture `strict` the spec side only observes the
    # reference, and replaying recorded traffic against it goes further than that (05 P3). An absent section and an empty column read identically to someone scanning the report, and
    # only one of them means "this was checked and there is nothing".
    # ---------------------------------------------------------------------------
    EQUIV_TITLE = "Equivalence (vs the legacy system)"
    equiv_section = ""
    if ac_lib and hasattr(ac_lib, "read_equiv_traces"):
        t = _read_text("sources.yaml") if os.path.exists("sources.yaml") else ""
        b = re.search(r"(?:(?<=[\n\r  ])|\A)reference:\n((?:(?:[ \t]+[^\n\r  ]*)?\n)*)", t)
        def ref_field(key):
            m = re.search(r"(?:(?<=[\n\r  ])|\A)" + _WS + r"+" + key + r":" + _WS + r"*([^\n\r  ]*)(?=[\n\r  ]|\Z)",
                          b.group(1)) if b else None
            return re.sub(r"^[\"']|[\"']\Z", "", re.split(_WS + "+#", js_trim(m.group(1)))[0]) if m else ""
        # Resolved as equiv.py's _posture, validate.py and the reference guard do; change them together.
        posture = ref_field("posture") or ("own-code" if ref_field("kind") == "own-code" else "observe")
        posture = posture if posture in ("strict", "observe", "own-code") else "strict"
        traces = ac_lib.read_equiv_traces(".")
        EQUIV_JUNIT = f"parity/{date}-equiv.xml"
        eq = ac_lib.read_ac_suite(EQUIV_JUNIT)

        if posture == "strict" and not traces:
            equiv_section = (f"\n## {EQUIV_TITLE}\n\nDoes not apply: `reference.posture` is `strict`, under which the "
                             "spec side only observes the reference; replaying recorded traffic against it needs `observe` "
                             "or `own-code` (05 P3). Parity for this project rests on the open and hidden suites and the "
                             "coverage figures above. This line exists so an absent section is not read as an unchecked one.\n")
        elif traces:
            by_feature = {}
            for tr in traces:
                by_feature.setdefault(tr["feature"], {"recorded": [], "replayed": 0, "green": 0, "red": []})["recorded"].append(tr["name"])
            replayed_total = green_total = 0
            red_cases = []
            if eq and not eq.get("unreadable"):
                for c in eq["cases"]:
                    # classname carries "<feature-id> <rule-id>…" — equiv.py writes it that way precisely
                    # so this join needs no second index.
                    feature = re.split(_WS + "+", c["classname"] or "")[0]
                    g = by_feature.get(feature)
                    replayed_total += 1
                    if c["state"] == "passed":
                        green_total += 1
                    if g:
                        g["replayed"] += 1
                        if c["state"] == "passed":
                            g["green"] += 1
                        else:
                            g["red"].append(c["caseName"] or c["name"])
                    if c["state"] != "passed":
                        red_cases.append(c)
            rows = []
            for f in sorted(by_feature, key=_pair_sort_key):
                g = by_feature[f]
                rows.append(f"| {f} | {len(g['recorded'])} | {g['replayed']} | {g['green']} | "
                            f"{', '.join(g['red']) if g['red'] else '—'} |")
            if eq and eq.get("unreadable"):
                header = (f"`{EQUIV_JUNIT}` exists but could not be read as JUnit ({eq['unreadable']}). Replay "
                          "results NOT reported — do not read their absence as a pass.")
            elif eq:
                header = (f"{len(traces)} trace(s) recorded, {replayed_total} replayed, {green_total} green. "
                          f"Source: `{EQUIV_JUNIT}`.")
            else:
                header = (f"{len(traces)} trace(s) recorded; **no `{EQUIV_JUNIT}` for today**, so none of them "
                          "has been replayed against the current build. Recorded is not green — run "
                          "`python3 scripts/equiv.py replay --all`.")
            unreplayed = len(traces) - replayed_total
            detail = []
            if eq and not eq.get("unreadable") and unreplayed > 0:
                detail.extend(["", f"**{unreplayed} recorded trace(s) were not replayed** in this run. They are "
                               "neither green nor red — nothing has checked them against the current build."])
            if red_cases:
                detail.extend(["", "Red:", *[f"- {c['name']}" for c in red_cases],
                               "", "A red trace is a real difference between the old system and the rebuild. Either the "
                               "rebuild is wrong, or the difference is intended — and if it is intended it goes on the "
                               "record: `python3 scripts/equiv.py accept \"<trace>\" --reason \"...\"`. `gate.py lock gate-5` "
                               "refuses while the newest run has a failure no decision names."])
            equiv_section = (f"\n## {EQUIV_TITLE}\n\n{header}\n\n"
                             "| Feature | Recorded | Replayed | Green | Red |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
                             + "\n".join(detail) + "\n")

    # A G6 run is part generated, part hand-written: the AC suite result and the
    # upstream re-mine are authored by a human or the orchestrator. Re-running on the
    # same date must not silently eat them, so keep every `## ` section this script
    # does not own.
    OWNED = [
        "Missing (in a done slice but not covered — investigate)",
        "Partial",
        "Upstream candidates (from re-mining — decide at next slice boundary)",
        "Descoped (by recorded decision)",
        "Slice progress",
        *([AC_TITLE] if ac_section else []),
        *([EQUIV_TITLE] if equiv_section else []),
    ]
    path = f"parity/{date}.md"
    preserved = ""
    if os.path.exists(path):
        kept = [chunk for chunk in re.split(r"\n(?=## )", _read_text(path))
                if chunk.startswith("## ") and js_trim(chunk[3:].split("\n")[0]) not in OWNED]
        if kept:
            preserved = "\n" + "\n".join(kept).rstrip(_JS_WS) + "\n"

    def slice_line(s):
        note = _lookup(notes, _get(s, "id"))
        return (f"- {js_str(_get(s, 'id'))} {js_str(_get(s, 'name'))}: {js_str(s['status'])}"
                + ("\n  - " + js_trim(note).replace("\n", "\n    ") if truthy(note) else ""))

    os.makedirs("parity", exist_ok=True)
    descoped_note = f", {len(buckets['descoped'])} descoped (not counted)" if buckets["descoped"] else ""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Parity report — {date}\n"
                "\n"
                f"Coverage: {len(buckets['covered'])}/{in_scope} covered ({pct}%), {len(buckets['partial'])} partial, "
                f"{len(buckets['missing'])} missing, {len(buckets['planned'])} planned{descoped_note}.\n"
                f"{ac_section}{equiv_section}\n"
                "## Missing (in a done slice but not covered — investigate)\n"
                f"{list_md(suspicious)}\n"
                "\n"
                "## Partial\n"
                f"{list_md(buckets['partial'])}\n"
                "\n"
                "## Upstream candidates (from re-mining — decide at next slice boundary)\n"
                f"{list_md(buckets['upstream'])}\n"
                "\n"
                "## Descoped (by recorded decision)\n"
                f"{list_md(buckets['descoped'])}\n"
                "\n"
                "## Slice progress\n"
                + ("\n".join(slice_line(s) for s in slices) or "- no slice plan yet") + "\n"
                f"{preserved}")
    ac_note = ""
    if counted:
        ac_note = (f" AC {counted['passed']}/{counted['total']} passed"
                   + (f" ({len(counted['rerunPasses'])} on rerun — {counted['label']})" if counted["rerunPasses"] else "") + ".")
    elif ac and not ac.get("unreadable"):
        ac_note = f" AC {ac['passed']}/{ac['total']} passed."
    em = re.search(r"^(\d+) trace\(s\) recorded, (\d+) replayed, (\d+) green", equiv_section, re.ASCII | re.MULTILINE)
    print(f"Wrote {path} — coverage {pct}%.{ac_note}"
          f"{f' Equivalence {em.group(3)}/{em.group(1)} green.' if em else ''}"
          f"{' Hand-written sections preserved.' if preserved else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
