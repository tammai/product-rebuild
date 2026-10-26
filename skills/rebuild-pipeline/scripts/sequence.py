#!/usr/bin/env python3
"""sequence.py — the logged-decision mechanism for slice ORDER. Run from the workbench root.

Usage:
  python3 scripts/sequence.py status
  python3 scripts/sequence.py init [--force]
  python3 scripts/sequence.py sync [--by <name>]
  python3 scripts/sequence.py reorder <Sn> (--before <Sm> | --after <Sm> | --first | --last)
                                           --reason "..." [--by <name>]

WHY THIS EXISTS

G3 states the Gate 2 decision outright: "'full features' is the fixed destination, so decide
SEQUENCE, not scope." But sequence had nowhere to live except the ARRAY ORDER of
plan/slices.yaml, which gate-2 hashes whole. So the one thing G3 calls the decision was the
most expensive thing in the pipeline to revise: a formal reopen, a new hash, and a moved pin
for every code repo holding the workbench as a submodule — all to say "build S6 before S4".
The predictable result is not that the order never changes. It is that it changes in
someone's head and nowhere on disk.

So the file splits in two along the line plan/progress.yaml and parity/flows/ already drew:

  plan/slices.yaml  — slice BOUNDARIES (features, depends_on, done_means). Gate 2, unchanged.
  plan/sequence.yaml — the SEQUENCE. Ungated, but every change carries a reason and a log
                       entry, exactly like `flows unlock` and a gate reopen.

Cheap in mechanism, deliberately not cheap in ceremony.

THE FROZEN HEAD

Reordering is a BETWEEN-SLICES act. Everything at or before the current slice is history and
does not move; only the pending tail does. That single rule is what keeps this script able to
be strict without ever standing between anyone and progress — it refuses while a slice is
in-progress, it refuses to move a slice that has shipped, and it refuses an order that
violates a depends_on edge gate-2 already locked. The dependency graph is machine-checkable;
the learning-value tradeoff G3 asks about is not, and this script does not pretend otherwise.

A mid-slice finding ("S6 should come before S4") does not need this script at all. It goes in
plan/progress.yaml's `notes:` for the slice you are IN, which parity.py already carries into
the report and slice_review.py surfaces as a reorder candidate. Observed when it is real,
acted on when it is safe.

It is a script and not a line in a doc because the log entry and the refusal rules are the
point: a doc can say "log your reorders", only code can refuse the reorder that has no reason.

LIBRARY AND CLI. The functions below are imported by slice_review, parity and validate; the CLI
is `main()`. Importing this module runs nothing.

Results that the JS returned as objects (`analyse`, `read_sequence`) are `_Result`: a dict that
also answers attribute access, so a caller can write `a["order"]` or `a.order`.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone

import yamlio

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def _read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


SEQUENCE_FILE = "plan/sequence.yaml"
DECISION_LOG = "plan/sequence-decisions.md"


class _Result(dict):
    """A dict that also answers `.key`, so callers ported from `a.order` and `a["order"]` both work."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def _read_yaml(p, fallback):
    if not os.path.exists(p):
        return fallback
    try:
        parsed = yamlio.load(_read_text(p))
        return fallback if parsed is None else parsed
    except Exception:
        return fallback


def _as_list(v):
    return v if isinstance(v, list) else []


def _join(seq, sep):
    return sep.join(str(x) for x in seq)


def _slice_id(s):
    return s.get("id") if isinstance(s, dict) else None


def positional_order(root="."):
    """Slice ids in plan/slices.yaml's positional order — the pre-sequence.yaml fallback."""
    slices = _as_list(_read_yaml(os.path.join(root, "plan/slices.yaml"), []))
    return [i for i in (_slice_id(s) for s in slices) if i]


def read_sequence(root="."):
    """The execution order, and where it came from. Every consumer goes through here so the
    fallback is identical everywhere: a workbench with no sequence.yaml (every one scaffolded
    before 0.15.0) keeps behaving exactly as it did, reading order off the array."""
    positional = positional_order(root)
    seq = _read_yaml(os.path.join(root, SEQUENCE_FILE), None)
    if not isinstance(seq, dict) or not isinstance(seq.get("order"), list):
        return _Result(order=positional, baseline=positional, source="positional", present=False)
    return _Result(
        order=seq["order"],
        baseline=seq["baseline"] if isinstance(seq.get("baseline"), list) else seq["order"],
        source="sequence.yaml", present=True)


def slice_statuses(root="."):
    """Slice id -> effective status, progress.yaml overlaying the gate-2 `status:`."""
    progress = _read_yaml(os.path.join(root, "plan/progress.yaml"), {}) or {}
    overlay = (progress.get("slices") if isinstance(progress, dict) else None) or {}
    if not isinstance(overlay, dict):
        overlay = {}
    out = {}
    for s in _as_list(_read_yaml(os.path.join(root, "plan/slices.yaml"), [])):
        sid = _slice_id(s)
        if sid:
            out[sid] = overlay.get(sid) or s.get("status") or "pending"
    return out


SHIPPED = {"done", "deployed"}


def analyse(root="."):
    """Everything the callers need to reason about movability, in one shape.

    `frozen_boundary` is the first index the pending tail starts at: one past the LAST
    non-pending slice in the current order, not the first. Taking the last matters — a slice
    built out of order leaves pending slices sitting behind it, and those are behind shipped
    work whatever their own status says. Freezing to the last non-pending slice is the
    conservative reading, and `status` reports the anomaly rather than quietly allowing a move
    into a region that is already history.
    """
    slices = _as_list(_read_yaml(os.path.join(root, "plan/slices.yaml"), []))
    by_id = {_slice_id(s): s for s in slices if _slice_id(s)}
    seq = read_sequence(root)
    order, baseline, source, present = seq["order"], seq["baseline"], seq["source"], seq["present"]
    statuses = slice_statuses(root)

    def status_of(sid):
        return statuses.get(sid) or "pending"

    last_non_pending = -1
    for i, sid in enumerate(order):
        if status_of(sid) != "pending":
            last_non_pending = i
    frozen_boundary = last_non_pending + 1

    in_progress = [sid for sid in order if status_of(sid) == "in-progress"]
    # Pending slices stuck behind shipped work: the order was overtaken in practice.
    stranded = [sid for sid in order[:frozen_boundary] if status_of(sid) == "pending"]

    # Which pending slices could run next, dependency-wise. This is the input to a between-slices
    # reorder conversation, and it is the one part of the tradeoff a machine can compute.
    shipped_ids = {sid for sid in order if status_of(sid) in SHIPPED}
    ready = [sid for sid in order[frozen_boundary:]
             if all(d in shipped_ids for d in _as_list((by_id.get(sid) or {}).get("depends_on")))]

    return _Result(slices=slices, by_id=by_id, order=order, baseline=baseline, source=source,
                   present=present, statuses=statuses, status_of=status_of,
                   frozen_boundary=frozen_boundary, in_progress=in_progress, stranded=stranded,
                   ready=ready, shipped_ids=shipped_ids)


def dependency_violation(order, by_id):
    """First depends_on edge the given order violates, or None. depends_on is gate-2 locked."""
    pos = {sid: i for i, sid in enumerate(order)}
    for sid in order:
        for dep in _as_list((by_id.get(sid) or {}).get("depends_on")):
            if dep not in pos:
                continue  # unknown dep — validate.py reports it against slices.yaml
            if pos[dep] > pos[sid]:
                return _Result(slice=sid, dep=dep)
    return None


# --- CLI below. Importing this module runs nothing. ---

def _iso_now():
    # JS toISOString(): millisecond precision, literal Z.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _write(path, text, mode="w"):
    # newline="\n" so Windows does not turn LF into CRLF in a file that is then committed.
    with open(path, mode, encoding="utf-8", newline="\n") as f:
        f.write(text)


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = list(sys.argv[1:] if argv is None else argv)

    def err(*lines):
        for line in lines:
            print(line, file=sys.stderr)

    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        err("No locks/pipeline.yaml here — run from the workbench root.")
        return 1
    cmd = args[0] if args else "status"
    if not cmd:
        cmd = "status"

    def arg_after(flag):
        if flag not in args:
            return None
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else None

    def has(flag):
        return flag in args

    by = arg_after("--by") or os.environ.get("USER") or "unknown"
    now = _iso_now()

    def write_sequence(baseline, order, recorded):
        os.makedirs("plan", exist_ok=True)
        _write(SEQUENCE_FILE,
               "# Slice execution order. Written by scripts/sequence.py — do not hand-edit.\n"
               "#\n"
               "# plan/slices.yaml holds the slice BOUNDARIES and is hashed whole by gate-2. This file holds\n"
               "# the SEQUENCE, which G3 calls the actual Gate 2 decision, so that revising it is a logged\n"
               "# decision rather than a formal gate reopen. Only the pending tail moves; see\n"
               "# plan/sequence-decisions.md for every change and its reason.\n"
               f"recorded: {recorded}\n"
               f"baseline: [{_join(baseline, ', ')}]\n"
               f"order:    [{_join(order, ', ')}]\n")

    def log_decision(body):
        os.makedirs("plan", exist_ok=True)
        if not os.path.exists(DECISION_LOG):
            _write(DECISION_LOG,
                   "# Slice sequence decisions\n\n"
                   "Every change to the slice execution order, in order, with its reason.\n"
                   "Written by `python3 scripts/sequence.py`. Do not edit by hand — the point of the log is that it\n"
                   "records what happened, not what someone remembers happening.\n\n"
                   "Slice *boundaries* are gate-2 locked and are not changed here; a change to what is IN\n"
                   "a slice is still a gate-2 reopen.\n\n")
        _write(DECISION_LOG, body, "a")

    def gate_locked(gid):
        p = os.path.join("locks", f"{gid}.yaml")
        if not os.path.exists(p):
            return False
        return re.search(r"^status: locked$", _read_text(p), re.M) is not None

    # ---------------------------------------------------------------- status
    if cmd == "status":
        a = analyse()
        # Emptiness is decided by plan/slices.yaml, not by the order: an overlay left behind after
        # the plan was emptied would otherwise print rows for slices that no longer exist.
        if not a.slices:
            print("No slice plan yet — plan/slices.yaml is empty or absent (normal before G3).")
            if a.present:
                print(f"{SEQUENCE_FILE} still names {_join(a.order, ', ')}. Reconcile: python3 scripts/sequence.py sync")
            return 0
        if not a.present:
            print(f"Slice order: reading plan/slices.yaml positionally — {SEQUENCE_FILE} does not exist.")
            print("Reordering is a gate-2 reopen until it does. Create it: python3 scripts/sequence.py init\n")
        orphans = [i for i in a.order if i not in a.by_id]
        missing = [i for i in (_slice_id(s) for s in a.slices) if i not in a.order]
        mark = {"done": "done", "deployed": "deployed", "in-progress": "IN PROGRESS", "pending": "pending"}
        for i, sid in enumerate([x for x in a.order if x in a.by_id]):
            s = a.by_id[sid]
            st = a.status_of(sid)
            frozen = i < a.frozen_boundary
            ready_mark = "  ← deps met" if not frozen and sid in a.ready else ""
            print(f"  {' ' if frozen else '·'} {str(sid).ljust(4)} {str(s.get('name') or '(unknown slice)').ljust(34)} "
                  f"{str(mark.get(st, st)).ljust(11)}{ready_mark}")
            if i + 1 == a.frozen_boundary and a.frozen_boundary < len(a.order):
                print(f"    {'─' * 58}  pending tail — the only part that moves")
        drift = _join(a.baseline, ",") != _join(a.order, ",")
        # Only claim agreement with the baseline when a baseline was actually recorded. Without
        # sequence.yaml, baseline and order are the same array by construction, and saying they
        # match would assert something no artifact establishes.
        tail = ("" if not a.present else
                (f" Order has diverged from the gate-2 baseline ({_join(a.baseline, ' → ')})." if drift
                 else " Order matches the gate-2 baseline."))
        print(f"\n  {a.frozen_boundary} of {len(a.order)} slice(s) frozen." + tail)
        if a.in_progress:
            print(f"  {_join(a.in_progress, ', ')} in progress — reordering is refused until it finishes "
                  "or is set back to pending. Reordering is a between-slices act.")
        if a.stranded:
            print(f"  ⚠ {_join(a.stranded, ', ')} still pending but positioned before shipped work — "
                  "the plan was overtaken. Reorder to move them into the tail, or record why they stay put.")
        if orphans or missing:
            # validate.py fails on the same condition; naming it here too matters because `status` is
            # where someone looks when the order surprises them, and "(unknown slice)" is not an answer.
            if orphans:
                print(f"  ⚠ {_join(orphans, ', ')} in the order but not in plan/slices.yaml.")
            if missing:
                print(f"  ⚠ {_join(missing, ', ')} in plan/slices.yaml but not in the order — never scheduled.")
            print("    Reconcile after a gate-2 reopen: python3 scripts/sequence.py sync")
        if os.path.exists(DECISION_LOG):
            print(f"  Decision log: {DECISION_LOG}")
        return 0

    # ------------------------------------------------------------------ init
    if cmd == "init":
        positional = positional_order()
        if not positional:
            err("plan/slices.yaml has no slices — nothing to sequence. Run this after G3 drafts the plan.")
            return 1
        if os.path.exists(SEQUENCE_FILE) and not has("--force"):
            err(f"{SEQUENCE_FILE} already exists. Reorder it with `reorder`, or pass --force to "
                "re-baseline from plan/slices.yaml (which discards the current order and the drift it records).")
            return 1
        write_sequence(positional, positional, now)
        log_decision(f"- **{now}** · initialised by {by}\n  - baseline {_join(positional, ' → ')}\n")
        print(f"Wrote {SEQUENCE_FILE} — baseline and order both {_join(positional, ' → ')}.")
        if not gate_locked("gate-2"):
            print("Note: gate-2 is not locked, so plan/slices.yaml can still change freely and this "
                  "baseline is provisional. Re-run with --force after the lock to record the real one.")
        print("Commit it. From here, reordering the pending tail is `python3 scripts/sequence.py reorder`, "
              "not a gate-2 reopen.")
        return 0

    # ------------------------------------------------------------------ sync
    # A gate-2 reopen that adds or drops a slice leaves this file a non-permutation, which
    # validate.py fails on. Reconciling is bookkeeping, not a decision — the decision was the
    # reopen — so it needs no reason. It is still logged, because a slice appearing at the end of
    # the tail by default is a placement somebody should see.
    if cmd == "sync":
        if not os.path.exists(SEQUENCE_FILE):
            err(f"{SEQUENCE_FILE} does not exist — run `python3 scripts/sequence.py init` first.")
            return 1
        positional = positional_order()
        known = set(positional)
        a = analyse()

        def keep(arr):
            return [i for i in arr if i in known]

        added = [i for i in positional if i not in a.order]
        removed = [i for i in a.order if i not in known]
        if not added and not removed:
            print("Already in sync with plan/slices.yaml — nothing to do.")
            return 0
        order = keep(a.order) + added
        baseline = keep(a.baseline) + added
        write_sequence(baseline, order, now)
        lines = (
            [f"  - added {i} ({(a.by_id.get(i) or {}).get('name') or '?'}) at the end of the tail — "
             "reorder it if that is not where it belongs" for i in added]
            + [f"  - removed {i}, no longer in plan/slices.yaml" for i in removed])
        log_decision(f"- **{now}** · synced with plan/slices.yaml by {by}\n" + "\n".join(lines) + "\n")
        print(f"Synced {SEQUENCE_FILE}.\n" + "\n".join(lines))
        if added:
            print("\nNew slices land last by default. Move them with `reorder` — that one needs a --reason.")
        return 0

    # --------------------------------------------------------------- reorder
    if cmd == "reorder":
        slice_id = args[1] if len(args) > 1 else None
        reason = arg_after("--reason")
        before, after = arg_after("--before"), arg_after("--after")
        first, last = has("--first"), has("--last")

        if not slice_id or slice_id.startswith("--"):
            err('Usage: reorder <Sn> (--before <Sm> | --after <Sm> | --first | --last) --reason "..."')
            return 1
        targets = [t for t in (before and "--before", after and "--after",
                               first and "--first", last and "--last") if t]
        if len(targets) != 1:
            err(f"Give exactly one destination: --before <Sm>, --after <Sm>, --first or --last (got {len(targets)}).")
            return 1
        if not reason:
            err('Reordering requires --reason "..." — it is a formal, logged event, same register as a gate reopen.',
                "Say what the build taught you that the Gate 2 order did not know. This is the only record",
                "that the plan moved and why; without it, drift is indistinguishable from the original plan.")
            return 1
        if not os.path.exists(SEQUENCE_FILE):
            err(f"{SEQUENCE_FILE} does not exist, so order still lives in plan/slices.yaml's array — which",
                "gate-2 hashes, making this a gate reopen rather than a logged decision.",
                "Create the overlay first: python3 scripts/sequence.py init")
            return 1

        a = analyse()

        def fail(*lines):
            err(*lines)
            return 1

        if slice_id not in a.order:
            return fail(f"{slice_id} is not in the slice plan.")

        # (1) The rule the whole design rests on: reordering is a between-slices act.
        if a.in_progress:
            return fail(
                f"{_join(a.in_progress, ', ')} is in progress — reordering is refused while a slice is being built.",
                "Reordering is a between-slices act: finish the slice (or set it back to `pending` in",
                "plan/progress.yaml if it is being abandoned), then reorder.",
                "",
                "Record the finding now so it survives to the boundary — plan/progress.yaml `notes:` on the",
                "slice you are IN. It reaches the parity report and the next slice review by itself.")
        # (2) The past is not reorderable.
        from_idx = a.order.index(slice_id)
        if from_idx < a.frozen_boundary:
            return fail(
                f"{slice_id} is {a.status_of(slice_id)} (or sits before shipped work) — the frozen head does not move.",
                f"Only the pending tail reorders: {_join(a.order[a.frozen_boundary:], ', ') or '(empty)'}.")

        # Resolve the destination index within the tail.
        rest = [i for i in a.order if i != slice_id]
        if first:
            insert_at = a.frozen_boundary
        elif last:
            insert_at = len(rest)
        else:
            anchor = before or after
            if anchor not in rest:
                return fail(f"Anchor {anchor} is not in the slice plan (or is the slice being moved).")
            anchor_idx = rest.index(anchor)
            # (3) A destination inside the frozen head is the same violation as moving a frozen slice.
            if anchor_idx < a.frozen_boundary:
                nxt = a.order[a.frozen_boundary] if a.frozen_boundary < len(a.order) else "(nothing pending)"
                return fail(f"{anchor} is in the frozen head — {slice_id} cannot be placed there.",
                            f"The tail starts at {nxt}.")
            insert_at = anchor_idx if before else anchor_idx + 1
        if insert_at < a.frozen_boundary:
            return fail("That destination is inside the frozen head — only the pending tail moves.")

        order = rest[:insert_at] + [slice_id] + rest[insert_at:]
        if _join(order, ",") == _join(a.order, ","):
            print(f"{slice_id} is already there — nothing to do.")
            return 0

        # (4) depends_on is gate-2 locked, so the graph check is free and is not negotiable here.
        v = dependency_violation(order, a.by_id)
        if v:
            return fail(f"That order puts {v['slice']} before {v['dep']}, which it depends on.",
                        "`depends_on` is gate-2 locked — changing it is a reopen, not a reorder.",
                        f"Proposed: {_join(order, ' → ')}")

        write_sequence(a.baseline, order, now)
        where = ("to the front of the tail" if first else "to the end" if last
                 else f"before {before}" if before else f"after {after}")
        log_decision(f"- **{now}** · moved {slice_id} {where}, by {by}\n"
                     f"  - {reason}\n"
                     f"  - was: {_join(a.order, ' → ')}\n"
                     f"  - now: {_join(order, ' → ')}\n")
        print(f"Moved {slice_id} {where}.")
        print(f"  was: {_join(a.order, ' → ')}")
        print(f"  now: {_join(order, ' → ')}")
        print(f"Logged to {DECISION_LOG}. Commit both files.")
        return 0

    err("Usage: sequence.py status | init [--force] | sync | "
        'reorder <Sn> (--before <Sm>|--after <Sm>|--first|--last) --reason "..."')
    return 1


if __name__ == "__main__":
    sys.exit(main())
