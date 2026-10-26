#!/usr/bin/env python3
"""slice_review.py — the between-slices standing report. Run from the workbench root.

Usage:
  python3 scripts/slice_review.py [<Sn>]      # defaults to the most recently shipped slice

Writes plan/slice-reviews/<Sn>.md and prints a summary. ADVISORY: it locks nothing, blocks
nothing, and starting the next slice without it is allowed. Its job is to make "where do we
stand" answerable at a slice boundary without anyone reconstructing it from scrollback.

WHY IT IS GENERATED AND NOT WRITTEN

Everything here comes off disk: plan/progress.yaml, plan/sequence.yaml, the AC suite's JUnit
output, matrix/features.yaml. None of it is composed. A slice review an agent writes is a
summary of what that agent believes it did, which is the failure `verifier`, `rubric-judge`
and g5-build.md's "a verification script names only what it RAN" all exist to prevent — and a
slice review is exactly the artifact that outlives the session that produced it. So the
script states facts and cites their source; judgement goes in the conversation on top of it,
and anything it could not establish says so rather than going quiet. That is also why it is a
script and not a paragraph in a doc: a doc can only ask for the facts, a script reads them.

WHAT IT ADDS THAT PARITY DOES NOT

parity.py answers "how much of the REFERENCE do we cover" — a coverage diff against the
matrix. Two questions it does not answer, and nothing else did either:
  - Does the whole product still run? Every per-slice deploy criterion asserts only that
    slice's features, so "did S3 break S1" had no home. Comparing this AC run against the
    previous one, by test name, gives it one.
  - Where does that put us on the roadmap? Position in the execution order, what is next,
    what is now orderable — the input to the between-slices reorder conversation.
"""

import datetime
import math
import os
import re
import sys

import yamlio

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def _read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


REVIEW_DIR = "plan/slice-reviews"
SHIPPED = {"done", "deployed"}

# Late-added sibling modules are imported guarded, the same way validate.py handles erd.py
# and playbook.py: a hand-upgraded workbench that copied this file without them should lose
# one section with an explanation, not die on an unresolved import before writing anything.
try:
    import sequence as seq_lib  # reported in the report
except ImportError:
    seq_lib = None
try:
    import acsuite as ac_lib  # reported in the report
except ImportError:
    ac_lib = None
try:
    import lane_plan as plan_lib  # section 2b is skipped
except ImportError:
    plan_lib = None

# JS String.prototype.trim: not Python's str.strip, which also strips \x1c-\x1f and \x85.
_JS_WS = " \t\n\v\f\r           " \
         "      　﻿"


def _trim(s):
    return s.strip(_JS_WS)


def _js_round(x):
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


# String.prototype.length counts UTF-16 units; the terminal wrap width is measured in them, so an
# astral character in a test name wraps where the Node original wrapped.
def _js_len(s):
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


# JS truthiness for values read out of hand-edited YAML: `[]` and `{}` are truthy there.
def _truthy(v):
    return not (v is None or v is False or v == "" or (isinstance(v, (int, float)) and (v == 0 or v != v)))


# `${x}` for a value out of YAML: the spelling a JS template literal gives (null, true, 10).
def _str(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if v.is_integer() and abs(v) < 1e21:
            return str(int(v))
    if isinstance(v, list):
        return ",".join("" if x is None else _str(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


# `${o.k}` where o is a mapping that may lack k: JS prints undefined, not an empty string.
def _show(o, k):
    return _str(o[k]) if isinstance(o, dict) and k in o else "undefined"


def _get(o, k):
    return o.get(k) if isinstance(o, dict) else None


def _list(v):
    return v if isinstance(v, list) else []


def _dict(v):
    return v if isinstance(v, dict) else {}


def _lookup(d, k):
    try:
        return d.get(k)
    except TypeError:
        return None  # an unhashable id (a YAML list) names nothing


def _read_yaml(p, fallback):
    if not os.path.exists(p):
        return fallback
    try:
        parsed = yamlio.load(_read_text(p))
        return fallback if parsed is None else parsed
    except Exception:
        return fallback


def _age_days(date, other):
    try:
        return (datetime.date.fromisoformat(date) - datetime.date.fromisoformat(other)).days
    except ValueError:
        return math.nan  # a file named for a date that does not exist


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = sys.argv[1:] if argv is None else list(argv)

    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1

    slices = _read_yaml("plan/slices.yaml", []) or []
    if not isinstance(slices, list) or not slices:
        print("plan/slices.yaml has no slices — nothing to review. This runs at a slice boundary, after G3.", file=sys.stderr)
        return 1
    by_id = {s["id"]: s for s in slices if isinstance(s, dict) and _truthy(s.get("id"))}
    progress = _dict(_read_yaml("plan/progress.yaml", {}) or {})
    slice_progress = _dict(progress.get("slices") or {})
    feature_progress = _dict(progress.get("features") or {})
    notes = _dict(progress.get("notes") or {})

    def status_of(sid):
        return _lookup(slice_progress, sid) or _get(by_id.get(sid), "status") or "pending"

    order = seq_lib.read_sequence()["order"] if seq_lib else [_get(s, "id") for s in slices]
    order_source = "plan/sequence.yaml" if seq_lib and seq_lib.read_sequence()["present"] else "plan/slices.yaml (positional)"

    wanted = argv[0] if argv else None
    shipped_in_order = [sid for sid in order if status_of(sid) in SHIPPED]
    slice_id = wanted or (shipped_in_order[-1] if shipped_in_order else None)
    if not slice_id:
        print("No slice has shipped yet, and none was named. Usage: python3 scripts/slice_review.py <Sn>", file=sys.stderr)
        return 1
    if slice_id not in by_id:
        print(f"{slice_id} is not in plan/slices.yaml.", file=sys.stderr)
        return 1
    slice_ = by_id[slice_id]
    slice_status = status_of(slice_id)
    # The LOCAL date, like every dated file in parity/ — see local_date() in acsuite.py. Inlined
    # rather than borrowed because acsuite is imported guarded; a UTC fallback would be the bug.
    _d = datetime.datetime.now()
    date = f"{_d.year}-{_d.month:02d}-{_d.day:02d}"

    # Facts are collected as data, then rendered twice — once as markdown, once for the terminal.
    # The terminal summary used to be produced by pattern-matching the markdown it had just built,
    # which dropped exactly the lines worth reading: a "1 regression(s)" header survived and the
    # regression's name, one line below it, did not.
    md_run, md_pressure = [], []   # markdown blocks
    term_run, term_pressure = [], []  # terminal lines

    def press(head, detail=None):
        term_pressure.append(head)
        md_pressure.append(f"- {head}" if detail is None else detail)

    # --- 1. does it run? -----------------------------------------------------
    # The cumulative question. Not "did this slice's tests pass" — every deploy criterion already
    # asserted that — but "is everything built so far still passing", and if not, what broke.
    matrix = _read_yaml("matrix/features.yaml", []) or []
    matrix = matrix if isinstance(matrix, list) else []
    feature_ids = [i for i in (_get(f, "id") for f in matrix) if _truthy(i)]
    run_headline = "NOT ESTABLISHED — see the report"
    if not ac_lib:
        md_run.append("- `scripts/acsuite.py` is missing from this workbench, so the AC suite was not read. "
                      "Copy it from the plugin's `skills/rebuild-pipeline/scripts/`. **Do not read its absence as a pass.**")
        term_run.append("scripts/acsuite.py missing — the suite was not read. Not a pass.")
    else:
        files = ac_lib.ac_junit_files()
        curr = ac_lib.read_ac_suite(files[0]["path"]) if files else None
        if not files:
            md_run.append("- No `parity/<date>-ac.xml` on disk, so **no AC result is reported here at all**. "
                          "This is not a pass and not a failure — nothing ran, or nothing was recorded. "
                          "See `g6-parity.md` step 1 for the command that produces it.")
            term_run.append("No AC JUnit file on disk. Nothing ran, or nothing was recorded — not a pass.")
        elif _truthy(_get(curr, "unreadable")):
            md_run.append(f"- `{files[0]['path']}` exists but could not be read as JUnit ({_str(curr['unreadable'])}). "
                          "Pass rate NOT reported — do not read its absence as a pass.")
            term_run.append(f"{files[0]['path']} is not readable as JUnit ({_str(curr['unreadable'])}). Not a pass.")
        else:
            # The newest run, not today's: a slice review is written at a boundary, which is rarely the
            # day the joint run happened and often crosses midnight (acsuite.py ac_junit_files says why
            # this report and parity.py answer "which run" differently). What must never happen is an
            # old file presented as current — so ANY non-zero age leads the section, negative included.
            # A negative age is a file dated ahead of this script's clock: before local_date() it was the
            # UTC-behind-local case, and it failed an `age_days > 0` test and printed "(today)".
            age_days = _age_days(date, files[0]["date"])
            if age_days != 0:
                if age_days > 0:
                    why = (f"the newest joint run is **{age_days} day(s) old** ({files[0]['date']}); "
                           "re-run the suite if anything shipped since")
                else:
                    ahead = "NaN" if math.isnan(age_days) else str(-age_days)
                    why = (f"the newest joint run is dated **{files[0]['date']}, {ahead} day(s) AHEAD of today ({date})** — a clock, "
                           "time-zone or copied-file problem. Check which run this is before trusting any number below")
                md_run.append(f"- ⚠️ **WARNING: no joint run for today ({date})** — {why}.")
                term_run.append(f"WARNING: no joint run for today ({date}) — newest is {files[0]['date']}" +
                                (f", {age_days} day(s) old." if age_days > 0 else ", AHEAD of today's date. Check which run this is."))
            rerun_path_fn = getattr(ac_lib, "ac_rerun_path", None)
            count_fn = getattr(ac_lib, "count_with_rerun", None)
            rerun_file = rerun_path_fn(files[0]["date"]) if rerun_path_fn else None
            counted = count_fn(curr, ac_lib.read_ac_suite(rerun_file) if rerun_file else None,
                               ac_lib.read_run_meta(ac_lib.run_meta_path(files[0]["date"])),
                               ac_lib.read_run_meta(ac_lib.run_meta_path(files[0]["date"], {"rerun": True}))) if count_fn else None
            eff = ({"cases": counted["cases"], "failures": [c for c in counted["cases"] if c["state"] == "failed"]}
                   if counted else curr)
            described = ac_lib.describe_counted(counted, files[0]["path"]) if counted else None
            rate = _js_round(curr["passed"] / curr["total"] * 100) if curr["total"] else 0
            run_headline = described["headline"] if described else (
                f"{curr['passed']}/{curr['total']} passed ({rate}%)" +
                (f", {curr['failed']} failed" if curr["failed"] else "") +
                (f", {curr['skipped']} skipped" if curr["skipped"] else ""))
            rerun_rec = _get(counted, "rerun")
            md_run.append(f"- **AC suite {run_headline}**" +
                          (" — a skipped AC is not a passing one" if curr["skipped"] else "") +
                          f". Source: `{files[0]['path']}`" +
                          (f" and `{rerun_rec['path']}`" if _truthy(rerun_rec) and not _truthy(rerun_rec.get("unreadable")) else "") +
                          (" (today)." if age_days == 0 else "."))
            if described:
                md_run.extend(described["lines"])
            if described and described["notGreen"]:
                term_run.append("NOT GREEN: the joint run skipped too much, or skipped for an unset environment variable — see the skip reasons.")
            if counted and len(counted["rerunPasses"]):
                term_run.append(f"{len(counted['rerunPasses'])} passed only on rerun — {counted['label']}" +
                                (f": {', '.join(c['repo'] for c in counted['changed'])} moved between the runs."
                                 if counted["label"] == "code-changed" else "."))

            grouped = ac_lib.group_by_feature(eff["cases"], feature_ids)
            by_feature, ungrouped = grouped["byFeature"], grouped["ungrouped"]
            per_slice = []
            for sid in [i for i in order if status_of(i) in SHIPPED]:
                passed = total = 0
                seen = False
                for f in _list(_get(by_id.get(sid), "features")):
                    g = by_feature.get(f)
                    if g:
                        passed += g["passed"]
                        total += g["total"]
                        seen = True
                per_slice.append(f"{sid} {passed}/{total}" if seen else f"{sid} —")
            if per_slice:
                md_run.append(f"- Per shipped slice: {' · '.join(per_slice)} "
                              "(`—` means no test case in this run joined to any of that slice's features)")
                term_run.append(f"Per slice: {' · '.join(per_slice)}")
            if ungrouped:
                md_run.append(f"- {len(ungrouped)} test case(s) did not join to any feature id, so they are "
                              "counted in the total but in no slice above "
                              f"({', '.join(c['name'] for c in ungrouped[:3])}"
                              f"{', …' if len(ungrouped) > 3 else ''}). The join is by feature id appearing in the JUnit "
                              "classname or test name; a missing row reads exactly like a feature with no tests, which is "
                              "why this line exists.")
                term_run.append(f"{len(ungrouped)} test case(s) joined to no feature — in the total, in no slice row.")

            # The previous boundary's run, with ITS rerun applied too — otherwise a flake that passed on
            # rerun last time and passes outright now reads as a recovery, and one that fails now reads
            # as a regression from a pass it never had in its joint run.
            prev_joint = ac_lib.read_ac_suite(files[1]["path"]) if len(files) > 1 else None
            prev_counted = (count_fn(prev_joint, ac_lib.read_ac_suite(ac_lib.ac_rerun_path(files[1]["date"])),
                                     ac_lib.read_run_meta(ac_lib.run_meta_path(files[1]["date"])),
                                     ac_lib.read_run_meta(ac_lib.run_meta_path(files[1]["date"], {"rerun": True})))
                            if prev_joint and count_fn else None)
            prev = {"cases": prev_counted["cases"]} if prev_counted else prev_joint
            cmp = ac_lib.compare_runs(prev, eff)
            prev_date = files[1]["date"] if len(files) > 1 else None
            if not cmp:
                md_run.append("- No previous AC run to compare against, so **regressions cannot be reported** — "
                              "this is the first recorded run, or the earlier file is unreadable.")
                term_run.append("No previous run to compare against — regressions could not be checked.")
            elif cmp["regressed"]:
                md_run.append(f"- **{len(cmp['regressed'])} regression(s) since `{prev_date}`** — passing then, not passing now:")
                for r in cmp["regressed"]:
                    md_run.append(f"  - {r['name']} (now {r['now']})")
                term_run.append(f"REGRESSED since {prev_date}: {' · '.join(r['name'] for r in cmp['regressed'])}")
            else:
                md_run.append(f"- No regressions since `{prev_date}`: every test passing then is passing now.")
                term_run.append(f"No regressions since {prev_date}.")
            if cmp and cmp["recovered"]:
                md_run.append(f"- {len(cmp['recovered'])} test(s) recovered since `{prev_date}`.")
            if cmp and cmp["removed"]:
                md_run.append(f"- {len(cmp['removed'])} test(s) present in `{prev_date}` are absent now "
                              f"({', '.join(cmp['removed'][:3])}{', …' if len(cmp['removed']) > 3 else ''}) — a rename or a "
                              "deletion, not counted as a regression either way. Worth a look if you did neither.")
                term_run.append(f"{len(cmp['removed'])} test(s) present on {prev_date} are gone — rename, or deletion?")
            # Failures already named as regressions are not repeated — listing the same test twice
            # under two headings is how a reader learns to skim past both. What is worth separating is
            # the failure that is NOT a regression: it was already failing last run, so nobody is going
            # to notice it from a delta, and it has now survived a whole slice.
            #
            # And a failing test that did not EXIST last run is neither: it is new, and calling it
            # "already failing" tells the reader it survived a slice when it was written in this one.
            standing = [f for f in eff["failures"] if not (cmp and any(r["name"] == f["name"] for r in cmp["regressed"]))]

            def is_new(f):
                return bool(cmp and f["name"] in cmp["added"])
            already = [f for f in standing if not is_new(f)]
            fresh = [f for f in standing if is_new(f)]
            if fresh:
                md_run.append(f"- Failing, new since `{prev_date}` — absent from that run, so neither a regression nor a standing failure:")
                for f in fresh:
                    md_run.append(f"  - {f['name']}")
                term_run.append(f"Failing, new since {prev_date}: {' · '.join(f['name'] for f in fresh)}")
            if already:
                md_run.append(f"- Also failing, and already failing on `{prev_date}` — no delta will surface these again:"
                              if cmp else "- Failing now:")
                for f in already:
                    md_run.append(f"  - {f['name']}")
                term_run.append(f"{'Still failing' if cmp else 'Failing'}: {' · '.join(f['name'] for f in already)}")

    # --- 1b. equivalence against the legacy system ---------------------------
    # Same question as the AC block above, one layer down and against a different authority: not
    # "does it do what the spec says" but "does it still produce what the OLD system produced".
    # Compared by trace name against the previous boundary for exactly the reason the AC run is —
    # every per-slice deploy criterion asserts only its own slice, so a trace this slice quietly
    # broke has no other place to surface.
    #
    # The lane does not apply to a third-party reference. Absent traces and an inapplicable lane
    # are reported differently on purpose: one of them means nobody recorded anything.
    if ac_lib and hasattr(ac_lib, "equiv_junit_files"):
        traces = ac_lib.read_equiv_traces(".") if hasattr(ac_lib, "read_equiv_traces") else []
        efiles = ac_lib.equiv_junit_files()
        if traces or efiles:
            ecurr = ac_lib.read_ac_suite(efiles[0]["path"]) if efiles else None
            if not efiles:
                md_run.append(f"- **Equivalence: {len(traces)} trace(s) recorded, none replayed.** No "
                              "`parity/<date>-equiv.xml` exists, so nothing has checked this build against the legacy "
                              "system. Recorded is not green — `python3 scripts/equiv.py replay --all`.")
                term_run.append(f"Equivalence: {len(traces)} recorded, 0 replayed — not checked against the legacy system.")
            elif _truthy(_get(ecurr, "unreadable")):
                md_run.append(f"- `{efiles[0]['path']}` exists but could not be read as JUnit ({_str(ecurr['unreadable'])}). "
                              "Equivalence NOT reported — do not read its absence as a pass.")
                term_run.append(f"{efiles[0]['path']} unreadable — equivalence not reported. Not a pass.")
            else:
                unreplayed = len(traces) - ecurr["total"]
                md_run.append(f"- **Equivalence {ecurr['passed']}/{ecurr['total']} traces green** against the legacy "
                              f"system{', ' + str(ecurr['failed']) + ' red' if ecurr['failed'] else ''}. {len(traces)} recorded"
                              f"{' — **' + str(unreplayed) + ' never replayed in this run**, neither green nor red' if unreplayed > 0 else ''}. "
                              f"Source: `{efiles[0]['path']}`.")
                term_run.append(f"Equivalence {ecurr['passed']}/{ecurr['total']} green" +
                                (f", {unreplayed} recorded but not replayed" if unreplayed > 0 else ""))
                eprev = ac_lib.read_ac_suite(efiles[1]["path"]) if len(efiles) > 1 else None
                ecmp = ac_lib.compare_runs(eprev, ecurr)
                eprev_date = efiles[1]["date"] if len(efiles) > 1 else None
                if not ecmp:
                    md_run.append("  - No previous equivalence run to compare against, so a trace that broke "
                                  "during this slice cannot be distinguished from one that was never green.")
                elif ecmp["regressed"]:
                    md_run.append(f"  - **{len(ecmp['regressed'])} trace(s) regressed since `{eprev_date}`** — "
                                  f"equivalent then, not now: {', '.join(r['name'] for r in ecmp['regressed'])}. This slice "
                                  "changed behavior the old system had.")
                    term_run.append(f"EQUIVALENCE REGRESSED since {eprev_date}: {' · '.join(r['name'] for r in ecmp['regressed'])}")
                else:
                    md_run.append(f"  - No equivalence regressions since `{eprev_date}`.")
                if ecurr["failed"]:
                    md_run.append("  - Red traces are real differences from the legacy system. If one is intended, "
                                  'it goes on the record — `python3 scripts/equiv.py accept "<trace>" --reason "..."` — and Gate 5 '
                                  "refuses to lock while any red trace has no decision naming it.")

    # --- 2. what shipped -----------------------------------------------------
    feature_name = {f["id"]: (f.get("name") or "") for f in matrix if isinstance(f, dict) and _truthy(f.get("id"))}
    slice_features = _list(slice_.get("features"))
    unrecorded = [i for i in slice_features if not _truthy(_lookup(feature_progress, i))]
    md_shipped = []
    for i in slice_features:
        fp = _lookup(feature_progress, i)
        md_shipped.append(
            f"- {_str(i)} {_str(_lookup(feature_name, i) or '(not in matrix/features.yaml)')} — **{_str(fp) if _truthy(fp) else 'no progress entry'}**" +
            ("" if _truthy(fp) else " *(falls back to the gate-1 mining status, which is about the REFERENCE)*"))

    # --- 2b. lane plans ------------------------------------------------------
    # Each lane worked under a PLAN.md that lane_plan.py wrote from the approved specs (E17b). The
    # spec gate cannot stop a lane rewriting its own approved spec — `*.md` is exempt from it — so
    # this is where that edit becomes visible: the `## Spec` section is re-hashed against
    # what lane_plan.py recorded. Advisory like everything here, but named, because a lane that
    # rewrote the spec it was approved against is the failure the plan exists to prevent.
    lane_plan_md = []
    lane_plans = plan_lib.read_lane_plans(slice_id) if plan_lib else None
    if lane_plans:
        for lane, rec in _dict(lane_plans.get("lanes") or {}).items():
            # A finished lane's plan was moved to the workbench by `lane_plan.py archive`; the copy is
            # checked exactly as the live one would have been, so archiving cannot hide an edited spec.
            live = os.path.join(rec["worktree"], "PLAN.md")
            archived = _get(rec, "archived")
            archived_path = _get(archived, "path")
            plan_path = archived_path if (not os.path.exists(live) and _truthy(archived_path) and os.path.exists(archived_path)) else live
            if not os.path.exists(plan_path):
                lane_plan_md.append(f"- {lane}: no PLAN.md in `{rec['worktree']}` and no archive recorded, so it was removed "
                                    f"by hand. Approved @ workbench {_show(rec, 'workbench_commit')} by {_show(rec, 'approved_by')}.")
                continue
            plan = _read_text(plan_path)
            rows = plan_lib.task_rows(plan)
            done = len([r for r in rows if r["status"] == "Done"])
            sm = re.search(r"^Status:\s*(\S+)", plan, re.M)
            status = sm.group(1) if sm else "(none)"
            edited = plan_lib.spec_hash(plan) != rec.get("spec_sha256")
            # The lane-verifier loop (E18). A lane with no PASS recorded reached the joint run unaudited,
            # or its audit was never written down; either way the review names it rather than assuming.
            rounds = _list(rec.get("verify"))
            last = rounds[-1] if rounds else None
            cap = getattr(plan_lib, "VERIFY_CAP", 3)
            verify_note = ("no verifier round recorded" if not rounds
                           else f"verifier {_show(last, 'verdict')} at round {_show(last, 'round')}/{cap}")
            lane_plan_md.append(f"- {lane}: {done}/{len(rows)} task rows Done · Status: {status} · {verify_note} · approved @ workbench "
                                f"{_show(rec, 'workbench_commit')} by {_show(rec, 'approved_by')}"
                                f"{' · ' + _str(rec['amendments']) + ' amendment(s)' if _truthy(rec.get('amendments')) else ''}"
                                f"{' · **`## Spec` differs from what was approved**' if edited else ''}")
            if hasattr(plan_lib, "VERIFY_CAP") and _get(last, "verdict") != "PASS":
                last_round = _show(last, "round")
                press(f"{lane}: {'last verifier round ' + last_round + ' was FAIL' if rounds else 'no verifier round recorded'}",
                      f"- **{lane} has no recorded verifier PASS** ({str(len(rounds)) + ' round(s), last FAIL' if rounds else 'none recorded'}). "
                      "Its diff reached the joint run without an independent audit against its PLAN.md, or the audit was never "
                      "recorded (`lane_plan.py record-verify`).")
            if edited:
                press(f"{lane}: its PLAN.md `## Spec` no longer matches the approved specs",
                      f"- **{lane}'s PLAN.md `## Spec` no longer matches what lane_plan.py wrote** from the specs approved @ "
                      f"workbench {_show(rec, 'workbench_commit')}. The spec gate cannot stop that edit, so this is the only place it shows. "
                      f"Diff `{plan_path}` against those specs; a legitimate change goes through `lane_plan.py --amend`.")
            if status != "approved":
                press(f"{lane}: PLAN.md is `Status: {status}`",
                      f"- **{lane}'s PLAN.md is `Status: {status}`**, so the spec gate blocks its non-trivial edits. "
                      "`amending` means the lane found the spec wrong and is waiting on a re-approval.")

    # --- 3. standing ---------------------------------------------------------
    #
    # COVERAGE IS COUNTED FROM plan/progress.yaml ONLY, and that is the whole point of this block.
    #
    # parity.py computes coverage with matrix/features.yaml's `status:` filling every gap, because
    # its job is a diff against the reference. But that field is GATE-1 MINING OUTPUT — how well the
    # REFERENCE covered each feature — and it shares the words `covered`, `partial` and `missing`
    # with this rebuild's progress vocabulary, so a matrix full of mined `covered` reads as a
    # finished rebuild before a line of code exists. parity.py warns about that for features inside
    # a shipped slice; features outside one are not covered by the warning at all.
    #
    # A standing report cannot inherit that ambiguity: "where do we stand" has one honest
    # denominator. So only an explicit progress entry counts here, the number is labelled
    # `recorded covered`, and the count of features with no entry is printed beside it so the gap
    # between this figure and parity's is visible rather than surprising.
    #
    # A `descoped` entry is a recorded ruling not to build the feature, so it leaves the denominator
    # here exactly as it does in parity.py — otherwise the two reports would disagree by the
    # descoped count with nothing saying why.
    recorded_covered = len([f for f in matrix if _lookup(feature_progress, _get(f, "id")) == "covered"])
    no_entry = len([f for f in matrix if not _truthy(_lookup(feature_progress, _get(f, "id")))])
    descoped = len([f for f in matrix if _lookup(feature_progress, _get(f, "id")) == "descoped"])
    in_scope = len(matrix) - descoped
    pct = _js_round(recorded_covered / in_scope * 100) if in_scope else 0
    shipped_slices = [i for i in order if status_of(i) in SHIPPED]
    pos = order.index(slice_id) if slice_id in order else -1
    pending_after = [i for i in order[pos + 1:] if status_of(i) not in SHIPPED]
    next_ = pending_after[0] if pending_after else None

    def name_of(i):
        return _str(_get(by_id.get(i), "name") or "")

    # --- 4. pressure ---------------------------------------------------------
    if _truthy(notes.get(slice_id)):
        note = _trim(_str(notes[slice_id]))
        press(f"Recorded during this slice: {note}",
              "- **Recorded during this slice** (`plan/progress.yaml` `notes:`):\n  > " + note.replace("\n", "\n  > "))
    if slice_status == "deployed":
        press("Slice is `deployed`, not `done` — a done_means clause is knowingly unmet. Which one, and is it coming back?",
              "- Slice is `deployed`, not `done` — a `done_means` clause is knowingly unmet. It still counts "
              "as shipped for creep detection, which is what `deployed` is for; say here which clause and "
              "whether it is coming back.")
    if seq_lib:
        a = seq_lib.analyse()
        orderable = [i for i in a["ready"] if i != next_]
        if orderable:
            listed = " · ".join(_trim(f"{i} {name_of(i)}") for i in orderable)
            press(f"Orderable now (deps already shipped, scheduled later): {listed}",
                  "- **Orderable now** (dependencies already shipped, currently scheduled later): "
                  f"{listed}. "
                  f"Moving one is `python3 scripts/sequence.py reorder <Sn> --before {next_ or '<Sm>'} --reason \"...\"` — "
                  "a logged decision, not a gate-2 reopen.")
        if a["present"] and ",".join(map(_str, a["baseline"])) != ",".join(map(_str, a["order"])):
            press(f"Order has diverged from the gate-2 baseline — see {seq_lib.DECISION_LOG}",
                  "- Execution order has diverged from the gate-2 baseline.\n"
                  f"  - Baseline: {' → '.join(map(_str, a['baseline']))}\n  - Now: {' → '.join(map(_str, a['order']))}\n"
                  f"  - Every move and its reason: `{seq_lib.DECISION_LOG}`")
        if a["stranded"]:
            stranded = ", ".join(map(_str, a["stranded"]))
            press(f"⚠ {stranded} still pending but positioned before shipped work",
                  f"- ⚠ {stranded} still pending but positioned before shipped work — the plan was "
                  "overtaken in practice. Reorder into the tail, or record why they stay put.")
    else:
        press("scripts/sequence.py missing — roadmap position and reorder candidates not computed",
              "- `scripts/sequence.py` is missing, so roadmap position and reorder candidates were not "
              "computed. Copy it from the plugin's `skills/rebuild-pipeline/scripts/`.")
    done_slice_features = list(dict.fromkeys(f for i in shipped_slices for f in _list(_get(by_id.get(i), "features"))))
    unrecorded_global = [i for i in done_slice_features if not _truthy(_lookup(feature_progress, i))]
    if unrecorded_global:
        sample = ", ".join(map(_str, unrecorded_global[:5])) + (", …" if len(unrecorded_global) > 5 else "")
        press(f"⚠ {len(unrecorded_global)} feature(s) in a shipped slice have no progress entry: {sample}",
              f"- ⚠ **{len(unrecorded_global)} feature(s) in a shipped slice have no `plan/progress.yaml` "
              "entry**, so they are not counted as covered above and parity.py falls back to their gate-1 "
              f"mining status instead. Record them under `features:`: {sample}")
    parity_reports = (sorted((f for f in os.listdir("parity") if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.md", f)), reverse=True)
                      if os.path.exists("parity") else [])
    if parity_reports:
        press(f"Creep, partial features and upstream candidates: see parity/{parity_reports[0]}",
              "- Scope creep, partial features and upstream candidates are not recomputed here — they are "
              f"`parity.py`'s sections. Latest: `parity/{parity_reports[0]}`.")
    else:
        press("No parity report on disk yet — creep and upstream candidates not looked at (python3 scripts/parity.py)",
              "- No parity report on disk yet (`python3 scripts/parity.py`), so creep and upstream candidates were "
              "not looked at for this boundary.")

    # --- 5. the runbook ------------------------------------------------------
    # The question nothing asked: what did this slice teach that plan/BUILD_RUNBOOK.md did not
    # already know? The runbook is required reading for every lane from S2 on, so it is the one
    # artifact whose staleness compounds — a lane reads it, believes it, and rediscovers the
    # truth the hard way. Asking at the boundary is asking while the answer is still in reach.
    #
    # `runbook_amended:` in plan/progress.yaml is what makes "nothing to add" distinguishable
    # from "nobody asked". Both look like an unchanged file otherwise, and only one is fine.
    runbook = os.path.join("plan", "BUILD_RUNBOOK.md")
    runbook_md = []
    amended = progress["runbook_amended"] if isinstance(progress.get("runbook_amended"), list) else []
    is_s1 = slice_id == "S1"
    if not os.path.exists(runbook):
        if is_s1:
            runbook_md.append(
                f"- **No `{runbook}` yet — this boundary is where it gets written.** S1 is the slice that "
                "discovered how the locked contracts, the harness scaffold and the reference's quirks "
                "actually combine, and none of it is written anywhere S2's lanes will read. Write it from "
                "what the S1 lanes REPORTED, not from memory (g5-build.md, between-slices step 5). "
                "`runbook_guard.py` blocks writes into a code repo once a slice after S1 is in progress "
                "without it, so this is also the thing standing between you and starting the next slice.")
        else:
            runbook_md.append(
                f"- ⚠ **No `{runbook}`, and {slice_id} is past S1.** Every lane in this slice rediscovered "
                "S1's lessons on its own. Write it now from what the lanes reported; the guard will block "
                "the next slice's code writes until it exists.")
    else:
        text = _read_text(runbook)
        amendments = [m.group(1) for m in re.finditer(r"^##\s+Amendment after (S[0-9]+)", text, re.M)]
        prev_shipped = [i for i in shipped_slices if i != slice_id]
        prev = prev_shipped[-1] if prev_shipped else None
        if prev:
            since = [x for x in amendments[(amendments.index(prev) if prev in amendments else -1) + 1:] if x]
        else:
            since = amendments
        if slice_id in amendments or slice_id in amended:
            runbook_md.append(f"- `{runbook}` was amended at this boundary" +
                              (f" (`## Amendment after {slice_id}`)." if slice_id in amendments else " (recorded in `runbook_amended:`)."))
        elif amended or amendments:
            runbook_md.append(f"- 🟡 **No amendment recorded for {slice_id}.** Amendments so far: "
                              f"{', '.join(map(_str, amendments if amendments else amended))}. "
                              "What did this slice teach that the runbook did not know? If genuinely nothing, add "
                              f"{slice_id} to `runbook_amended:` in `plan/progress.yaml` so the next reader can tell "
                              '"nothing to add" from "nobody asked" — those look identical in the file itself.')
        else:
            runbook_md.append(f"- 🟡 **`{runbook}` exists but carries no `## Amendment after S<n>` section "
                              "and `runbook_amended:` is empty.** Either no boundary has revisited it since it was "
                              "written, or boundaries have and did not say so. Both are worth a minute now.")
        if since:
            runbook_md.append(f"- Amendments since {prev or 'it was written'}: {', '.join(since)}.")
        runbook_md.append("- Append, never rewrite. The runbook is a record of what was learned and "
                          "when; rewriting destroys the sequence, which is what tells a reader whether a claim "
                          "predates the thing they are debugging.")

    # --- write ---------------------------------------------------------------
    def bar(n, m):
        w = 14
        on = _js_round(n / m * w) if m else 0
        return "█" * on + "░" * (w - on)

    os.makedirs(REVIEW_DIR, exist_ok=True)
    path = os.path.join(REVIEW_DIR, f"{slice_id}.md")
    slice_name = _show(slice_, "name")
    shipped_block = "\n".join(md_shipped) if md_shipped else "- this slice lists no features"
    learning = _list(slice_.get("learning_goals"))
    extras = (
        (f"\nLane plans (`plan/lane-plans/{slice_id}.yaml`):\n\n" + "\n".join(lane_plan_md) + "\n" if lane_plan_md else "") +
        (f"\n{len(unrecorded)} of them have no `plan/progress.yaml` entry. Record them under `features:` — until then they count as uncovered here and fall back to mining status in the parity report.\n" if unrecorded else "") +
        (f"\nLearning goals: {' · '.join(map(_str, learning))}\n" if learning else ""))
    descoped_note = f", {descoped} descoped (not counted)" if descoped else ""
    noentry_note = f"; {no_entry} of {len(matrix)} matrix features have none yet" if no_entry else ""
    order_lines = "\n".join(f"{'→' if i == slice_id else ' '} {_str(i)} {name_of(i)} — {_str(status_of(i))}" for i in order)
    next_label = f"{next_} {name_of(next_)}" if next_ else "nothing pending — every slice has shipped"
    body = f"""# Slice review — {slice_id} {slice_name}

Generated {date} by `scripts/slice_review.py` from `plan/progress.yaml`, `{order_source}`,
`matrix/features.yaml` and the AC suite's JUnit output. Nothing here is composed; judgement
goes in the conversation on top of it.

**Advisory.** This locks nothing and blocks nothing. Slice boundaries are where the plan can
still change cheaply, which is the only reason to stop and look.

Status: **{_str(slice_status)}** · position {pos + 1} of {len(order)} in the execution order.

> done_means: {_str(slice_.get("done_means")) if _truthy(slice_.get("done_means")) else "(not stated)"}

## 1. Does it run?

The cumulative question — not "did this slice's tests pass", which its deploy criterion already
asserted, but "is everything built so far still passing".

{chr(10).join(md_run)}

## 2. What shipped

{shipped_block}
{extras}
## 3. Where that puts us

```
{bar(len(shipped_slices), len(order))}  {len(shipped_slices)} of {len(order)} slices shipped
{bar(recorded_covered, in_scope)}  {recorded_covered} of {in_scope} features recorded covered ({pct}%){descoped_note}
```

Coverage here counts **only explicit `plan/progress.yaml` entries**{noentry_note}.
`parity.py` reports a different figure over the same matrix because it fills gaps with
`matrix/features.yaml`'s `status:`, which is gate-1 mining output — how well the *reference*
covered each feature. Both are correct for their own question; this one is about the rebuild.

Order ({order_source}):

{order_lines}

Next: **{next_label}**

## 4. Pressure on the plan

{chr(10).join(md_pressure)}

## 5. What did this slice teach the runbook?

`plan/BUILD_RUNBOOK.md` is required reading for every backend, frontend and infra lane from
S2 on, which makes it the one artifact whose staleness compounds: a lane reads it, believes
it, and rediscovers the truth the expensive way. This is the boundary where the answer is
still in reach.

{chr(10).join(runbook_md)}

## The decision

Accept this slice and start {next_ or "GP"}, or name what has to come back first. Either way it
is yours — nothing here enforces it. If the plan should change, do it now, at the boundary:
slice *order* is `python3 scripts/sequence.py reorder` (logged, cheap); what is IN a slice is still a
gate-2 reopen (`python3 scripts/gate.py reopen gate-2 --reason "..."`).
"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)

    # --- terminal summary ----------------------------------------------------
    # Rendered from the same collected facts as the markdown, not by pattern-matching it.
    indent, width = " " * 12, 88

    def wrap(s, first, cont=indent):
        lines = []
        line = ""
        for w in re.split(r"\s+", _str(s)):
            if line and _js_len(line + " " + w) > width:
                lines.append(line)
                line = ""
            line = f"{line} {w}" if line else w
        if line:
            lines.append(line)
        return "\n".join((first + l) if i == 0 else (cont + l) for i, l in enumerate(lines))

    head = f"── SLICE REVIEW · {slice_id} {slice_name} "
    print(f"\n{head}{'─' * max(3, 74 - _js_len(head))}\n")
    print(wrap(run_headline, "  Runs?     "))
    for l in term_run:
        print(wrap(l, indent))
    print(f"\n  Shipped   {len(slice_features)} feature(s) · slice is {_str(slice_status)}")
    print(f"\n  Standing  {bar(len(shipped_slices), len(order))}  {len(shipped_slices)}/{len(order)} slices shipped")
    print(f"{indent}{bar(recorded_covered, in_scope)}  {recorded_covered}/{in_scope} features recorded covered ({pct}%)" +
          (f", {descoped} descoped" if descoped else ""))
    print(wrap(f"Next: {_str(next_) + ' ' + name_of(next_) if next_ else 'nothing pending'}", indent))
    if len(pending_after) > 1:
        print(wrap(f"Then: {' · '.join(map(_str, pending_after[1:]))}", indent))
    if term_pressure:
        print("\n  Pressure")
        for p in term_pressure:
            print(wrap(p, indent + "· ", indent + "  "))
    print(f"\nWrote {path} — advisory; it locks nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
