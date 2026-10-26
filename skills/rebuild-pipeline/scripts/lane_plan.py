#!/usr/bin/env python3
"""lane_plan.py — write a G5 build lane's PLAN.md from the slice specs you approved (E17b, 0.29.0).
Run from the workbench root, right after the slice's specs are approved and before the lane
is dispatched.

  python3 scripts/lane_plan.py S3 billing-backend --worktree ../app-S3-billing \\
       --specs plan/specs/S3/billing.md,plan/specs/S3/invoicing.md
  python3 scripts/lane_plan.py S3 billing-backend --worktree ../app-S3-billing \\
       --specs plan/specs/S3/billing.md --amend --reason "AC 4 contradicted R-BILL-002"
  python3 scripts/lane_plan.py archive S3 billing-backend     # slice end: plan leaves the worktree

WHY THIS EXISTS. The plugin's spec-gate-guard blocks any edit over ~20 lines in a code repo
until PLAN.md at the worktree root says `Status: approved`, so a lane with no plan is blocked
on its first real edit. The human
approval the gate wants already exists — you approve a slice's specs before any code
(g5-build.md; autopilot halts for it) — but it lived in the workbench and never reached the
file the gate reads. A lane told to write its own plan would be approving itself: `*.md` is on
the guard's exempt list, so nothing would stop it, and the gate would then report an approval
no person gave. So the plan is written here, by script, at the approval moment, and carries
where the approval came from (`Approved:` — spec paths, workbench commit, approver).

THE FORMAT: `Status:` and `Branch:` are what the guard reads (`^Status:\\s*(\\S+)`,
`^Branch:\\s*(\\S+)` — hooks/scripts/hooklib.py PLAN_STATUS and PLAN_BRANCH). This script is
vendored into each workbench and runs alone, so it cannot import them; PLAN_STATUS and
PLAN_BRANCH below are its own copy, and eval/lane_plan.py imports both sides and fails if they
stop agreeing. If you change one, change both. `archive` reads the rest.
Tasks are one row per acceptance criterion, so `Done` means the same thing in the plan, in the
AC→test mapping and in the per-rule parity report.

It refuses rather than guesses: specs with uncommitted changes (the approval would point at
text no commit holds), a worktree on a branch other than slice/<Sn>-<lane>, and an existing
PLAN.md with unfinished rows (a plan with work in it is never overwritten). Every write is recorded
in plan/lane-plans/<Sn>.yaml with a sha256 of the plan's `## Spec` section, which
slice_review.py re-checks: the guard cannot stop a lane editing its own approved spec, since
`*.md` is exempt, so the slice boundary is where that edit becomes visible.

It is a script and not a line in a doc because the approval has to be written by something
that is not the lane: a doc can only ask the lane to behave, a script writes the file the gate
reads.
"""

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident. Undecodable bytes become U+FFFD, as Node's utf8
# read did, so a stray byte in a spec does not abort the plan.
def _read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


# Written with newline="\n" so Windows does not turn the plan's LF into CRLF: the hash of
# `## Spec` and the sha256 of the archived plan are taken over LF text.
def _write_text(p, text):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# The spec gate's own patterns, copied from hooks/scripts/hooklib.py. Not imported: this script
# is vendored into workbenches and must run alone. eval/lane_plan.py fails if the two diverge.
PLAN_STATUS = re.compile(r"^Status:\s*(\S+)", re.M)
PLAN_BRANCH = re.compile(r"^Branch:\s*(\S+)", re.M)

# JS String.prototype.trim strips these and no other characters; Python's str.strip also strips
# \x1c-\x1f and \x85, which a spec line may carry, so a plan written here would differ from
# the one the Node original wrote.
_JS_WS = " \t\n\v\f\r           " \
         "      　﻿"


def _trim(s):
    return s.strip(_JS_WS)


# Section boundaries of a PLAN.md this script wrote. Spec headings are demoted two levels when
# embedded (below), so `## Tasks` and `## Amendments` are the only h2s after `## Spec`.
def spec_section(plan):
    m = re.search(r"^## Spec\n([\s\S]*?)(?=^## Tasks\s*$)", plan, re.M)
    return m.group(1) if m else None


def spec_hash(plan):
    s = spec_section(plan)
    return None if s is None else hashlib.sha256(s.encode("utf-8")).hexdigest()


def task_rows(plan):
    m = re.search(r"^## Tasks\s*\n([\s\S]*?)(?=^## |\Z)", plan, re.M)
    sec = m.group(1) if m else ""
    rows = []
    for l in sec.split("\n"):
        if not re.match(r"^\|\s*[0-9]+\s*\|", l):
            continue
        # Split on unescaped pipes only: an AC text may carry `\|`.
        cells = [_trim(c) for c in re.split(r"(?<!\\)\|", l)[1:-1]]
        rows.append({
            "n": int(cells[0]), "task": cells[1] if len(cells) > 1 else "",
            "status": cells[2] if len(cells) > 2 else "", "notes": cells[3] if len(cells) > 3 else "",
        })
    return rows


def read_lane_plans(slice_id, root="."):
    p = os.path.join(root, "plan", "lane-plans", f"{slice_id}.yaml")
    if not os.path.exists(p):
        return None
    try:
        rec = json.loads(re.sub(r"^#.*\n", "", _read_text(p), flags=re.M))
    except ValueError:
        return None
    # Anything but an object is as unusable as unparseable text: callers index `.lanes`.
    return rec if isinstance(rec, dict) else None


# The acceptance criteria of one spec: the list items under `## Acceptance criteria`, the same
# section and item shape validate.py counts for its rule_id figures, numbered heading
# (`## 5. Acceptance criteria`) included. Change the heading pattern in both together.
# The heading line itself is skipped: `5. Acceptance criteria` matches the list-item pattern, and the
# Node original turned it into the plan's first task row (and validate counted it as a criterion
# with no rule_id).
def _acceptance_criteria(text):
    sec = None
    for c in re.split(r"^##\s+", text, flags=re.M)[1:]:
        if re.match(r"^([0-9]+[a-z]?\.\s*)?acceptance criteria\s*\Z", _trim(c.split("\n")[0]), re.I):
            sec = c
            break
    if sec is None:
        return []
    return [_trim(re.sub(r"^\s*(?:[0-9]+\.|[-*])\s+", "", l, count=1))
            for l in sec.split("\n")[1:] if re.match(r"^\s*(?:[0-9]+\.|[-*])\s+\S", l)]


_REC_HEADER = "# Written by scripts/lane_plan.py; read by slice_review.py. Do not hand-edit.\n"

_JS_NUMBER = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


# Number(x) for a CLI argument: "" is 0, junk is NaN, hex is read. `float()` alone would accept
# "1_0", "nan" and "infinity" spellings that Node refuses, so an argument that was rejected by the
# Node original would be taken here.
def _js_number(s):
    if s is None:
        return math.nan
    s = _trim(s)
    if s == "":
        return 0.0
    if _JS_NUMBER.fullmatch(s):
        return float(s)
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", s):
        return float(int(s, 16))
    if re.fullmatch(r"0[oO][0-7]+", s):
        return float(int(s[2:], 8))
    if re.fullmatch(r"0[bB][01]+", s):
        return float(int(s[2:], 2))
    if s in ("Infinity", "+Infinity"):
        return math.inf
    if s == "-Infinity":
        return -math.inf
    return math.nan


# What JSON.stringify writes for a number: integral values without ".0", NaN and ±Infinity as null.
def _json_number(x):
    if math.isnan(x) or math.isinf(x):
        return None
    return int(x) if x == int(x) else x


def _iso_now():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _local_date():
    d = datetime.now()
    return f"{d.year}-{d.month:02d}-{d.day:02d}"


def _opt(args, name):
    if name not in args:
        return None
    i = args.index(name)
    return args[i + 1] if i + 1 < len(args) else None


def _positionals(args, value_flags):
    # The previous argument decides: a value belongs to its flag, not to the positionals.
    return [a for i, a in enumerate(args)
            if not a.startswith("--") and not (i > 0 and args[i - 1] in value_flags)]


def _die(prefix, msg):
    print(f"{prefix}: {msg}", file=sys.stderr)
    return 1


def _save_record(slice_id, rec):
    _write_text(os.path.join("plan", "lane-plans", f"{slice_id}.yaml"),
                _REC_HEADER + json.dumps(rec, indent=2, ensure_ascii=False) + "\n")


# `archive` (1.0.0): the slice-end half of a plan's life. Until 1.0.0 a finished PLAN.md left the
# worktree through another plugin's cleanup step. Nothing does that now, and a plan left in the
# worktree is merged into the code repo with the lane's last commit, carrying a stale
# `Status: approved` that the spec gate would honour for the next lane cut from that tree. So the
# plan moves to the workbench, which is where the record of what was approved belongs anyway, and
# the code repo's tree carries no PLAN.md after the slice.
#
# It refuses a plan with unfinished rows or `Status: amending`: archiving is the claim that the
# lane is done. An edited `## Spec` does NOT stop it — the copy is the evidence — but it is
# recorded, and slice_review.py names it.
def _archive(args):
    def die(msg):
        return _die("lane-plan archive", msg)
    slice_id, lane = (_positionals(args, ()) + [None, None])[:2]
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        return die("no locks/pipeline.yaml here — run from the workbench root.")
    if not slice_id or not lane:
        return die("usage: lane_plan.py archive <Sn> <lane>")
    rec = read_lane_plans(slice_id)
    lrec = ((rec or {}).get("lanes") or {}).get(lane)
    if not lrec:
        return die(f"no plan recorded for {slice_id} {lane}.")
    if lrec.get("archived"):
        return die(f"{slice_id} {lane} was already archived to {lrec['archived'].get('path')}.")
    plan_path = os.path.join(lrec["worktree"], "PLAN.md")
    if not os.path.exists(plan_path):
        return die(f"no PLAN.md in {lrec['worktree']}.")
    plan = _read_text(plan_path)
    sm = PLAN_STATUS.search(plan)
    status = sm.group(1) if sm else "(none)"
    if status != "approved":
        return die(f"{plan_path} is Status: {status}. Only an approved plan with every row Done is archived.")
    rows = task_rows(plan)
    open_rows = [r for r in rows if r["status"] != "Done"]
    if open_rows:
        return die(f"{len(open_rows)} of {len(rows)} task row(s) are not Done (first: row {open_rows[0]['n']}).")
    dest = os.path.join("plan", "lane-plans", "archive", f"{slice_id}-{lane}.md")
    os.makedirs(os.path.join("plan", "lane-plans", "archive"), exist_ok=True)
    _write_text(dest, plan)
    os.unlink(plan_path)
    # A plan the lane committed is tracked: removing the file alone leaves the deletion unstaged,
    # and the next `git add -p` would miss it.
    staged = False
    try:
        quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "check": True}
        subprocess.run(["git", "-C", lrec["worktree"], "ls-files", "--error-unmatch", "PLAN.md"], **quiet)
        subprocess.run(["git", "-C", lrec["worktree"], "rm", "-q", "--cached", "PLAN.md"], **quiet)
        staged = True
    except (subprocess.CalledProcessError, OSError):
        pass  # untracked: the unlink was the whole removal
    lrec["archived"] = {
        "path": dest.replace("\\", "/"), "at": _iso_now(), "rows": len(rows),
        "sha256": hashlib.sha256(plan.encode("utf-8")).hexdigest(),
        "spec_edited": spec_hash(plan) != lrec.get("spec_sha256"),
    }
    _save_record(slice_id, rec)
    print(f"{slice_id} {lane}: {len(rows)} row(s) Done, archived to {dest}" +
          (" — WARNING: the plan's ## Spec differs from what was approved; slice-review will name it."
           if lrec["archived"]["spec_edited"] else "") +
          (f"\nPLAN.md was tracked: its removal is staged in {lrec['worktree']}. Commit it with the lane's last commit."
           if staged else ""))
    return 0


# git's stderr is left attached to ours: a refused `ls-files --error-unmatch` prints git's own
# "pathspec did not match" before our message, as the Node original's execFileSync did.
def _git(cwd, *a):
    r = subprocess.run(["git", "-C", cwd, *a], stdout=subprocess.PIPE, text=True, encoding="utf-8", check=True)
    return _trim(r.stdout)


def _write_plan(args):
    def die(msg):
        return _die("lane-plan", msg)
    value_flags = ("--worktree", "--specs", "--reason", "--branch")
    slice_id, lane = (_positionals(args, value_flags) + [None, None])[:2]
    amend = "--amend" in args

    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        return die("no locks/pipeline.yaml here — run from the workbench root.")
    if not slice_id or not lane or not _opt(args, "--worktree") or not _opt(args, "--specs"):
        return die('usage: lane_plan.py <Sn> <lane> --worktree <path> --specs <a.md,b.md> [--amend --reason "..."] [--branch <name>]')
    if amend and not _opt(args, "--reason"):
        return die("--amend needs --reason: the amendment log is the only record the plan's shape changed.")

    worktree = os.path.abspath(_opt(args, "--worktree"))
    specs = [s for s in (_trim(s) for s in _opt(args, "--specs").split(",")) if s]

    # The approval must point at committed text.
    for s in specs:
        if not os.path.exists(s):
            return die(f"no such spec {s}")
        if not s.replace("\\", "/").startswith(f"plan/specs/{slice_id}/"):
            return die(f"{s} is not under plan/specs/{slice_id}/")
    try:
        dirty = _git(".", "status", "--porcelain", "--", *specs)

        def tracked(s):
            try:
                _git(".", "ls-files", "--error-unmatch", s)
                return True
            except (subprocess.CalledProcessError, OSError):
                return False
        untracked = [s for s in specs if not tracked(s)]
    except (subprocess.CalledProcessError, OSError):
        return die("the workbench is not a git repository, so there is no commit for the approval to point at.")
    if untracked:
        return die(f"not committed: {', '.join(untracked)}. Commit the approved specs first.")
    if dirty:
        return die(f"uncommitted changes to approved specs:\n{dirty}\nCommit them first — the approval has to point at text a commit holds.")
    commit = _git(".", "rev-parse", "--short", "HEAD")
    try:
        approver = _git(".", "config", "user.name")
    except (subprocess.CalledProcessError, OSError):
        approver = ""  # unset
    if not approver:
        return die("git user.name is unset in the workbench, so the approval would name nobody.")

    # The worktree, on the lane's own branch.
    try:
        branch = _git(worktree, "branch", "--show-current")
    except (subprocess.CalledProcessError, OSError):
        return die(f"{worktree} is not a git worktree.")
    expected = _opt(args, "--branch") or f"slice/{slice_id}-{lane}"
    if branch != expected:
        return die(f"{worktree} is on '{branch or '(detached)'}', expected '{expected}'. One lane, one worktree, one "
                   f"branch: the guard reads PLAN.md per worktree, so two lanes sharing a checkout would share a plan.")

    plan_path = os.path.join(worktree, "PLAN.md")
    existing = _read_text(plan_path) if os.path.exists(plan_path) else None
    old_rows = task_rows(existing) if existing else []
    if existing and not amend and any(r["status"] != "Done" for r in old_rows):
        return die(f"{plan_path} has unfinished rows. Finish or archive that plan, or use --amend if the approved specs changed.")
    if amend and not existing:
        return die(f"--amend: there is no {plan_path} to amend.")

    # Spec text, verbatim apart from headings demoted two levels so the plan's own `## Tasks`
    # stays the only h2 after `## Spec`.
    date = _local_date()
    spec_body = "\n".join(
        f"### {s.replace(chr(92), '/')}\n\n" +
        _trim(re.sub(r"^(#{1,4})(\s)", r"##\1\2", _read_text(s), flags=re.M)) + "\n"
        for s in specs)
    acs = []
    for s in specs:
        mod = re.sub(r"\.md\Z", "", re.split(r"[\\/]", s)[-1])
        for i, ac in enumerate(_acceptance_criteria(_read_text(s))):
            acs.append(re.sub(r"(?<!\\)\|", r"\\|", f"{mod} AC{i + 1}: {ac}"))
    if not acs:
        return die("the specs carry no `## Acceptance criteria` items, so there is nothing to make task rows from.")

    # On amend, a row keeps its status only when its criterion text is unchanged; a changed
    # criterion is a new row, which is how an invalidated `Done` goes back to `Not started`.
    old_by_task = {}
    for r in old_rows:
        old_by_task[r["task"]] = r
    rows = []
    for i, task in enumerate(acs):
        keep = old_by_task.get(task) if amend else None
        rows.append(f"| {i + 1} | {task} | {(keep or {}).get('status') or 'Not started'} | {(keep or {}).get('notes') or ''} |")
    added = len([t for t in acs if t not in old_by_task]) if amend else 0
    removed = len([r for r in old_rows if r["task"] not in acs]) if amend else 0
    pm = re.search(r"^## Amendments\n([\s\S]*)$", existing, re.M) if existing else None
    prior_amendments = _trim(pm.group(1)) if pm else ""
    amend_line = f"- {date} @ workbench {commit}, {approver}: {_opt(args, '--reason')} (rows added {added}, dropped {removed})" if amend else None

    approved = ", ".join(s.replace("\\", "/") for s in specs)
    plan = "\n".join([
        f"# Plan: {slice_id} {lane}",
        "",
        "Status: approved",
        f"Branch: {branch}",
        f"Approved: {approved} @ workbench {commit} — {approver}, {date}",
        "",
        "Written by the rebuild pipeline's lane_plan.py from the slice specs approved in the workbench. " +
        "Work the task rows; do not edit Status, Branch, Approved or the Spec section. If the spec is " +
        "wrong, set `Status: amending` and report — that is the only Status edit a lane may make.",
        "",
        "## Spec",
        "",
        spec_body,
        "## Tasks",
        "",
        "| # | Task | Status | Notes |",
        "|---|------|--------|-------|",
        *rows,
        *(["", "## Amendments", "", *([prior_amendments] if prior_amendments else []),
           *([amend_line] if amend_line else [])] if prior_amendments or amend_line else []),
        "",
    ])
    _write_text(plan_path, plan)

    # The record slice_review checks against. JSON in a .yaml file: valid YAML, and readable here
    # without a YAML parser, so this script runs in a workbench whose vendored yamlio is absent.
    rec_path = os.path.join("plan", "lane-plans", f"{slice_id}.yaml")
    os.makedirs(os.path.join("plan", "lane-plans"), exist_ok=True)
    rec = read_lane_plans(slice_id) or {"slice": slice_id, "lanes": {}}
    lanes = rec.setdefault("lanes", {})
    prior = lanes.get(lane) or {}
    entry = {
    }
    try:
        rel_worktree = os.path.relpath(worktree, ".")
    except ValueError:
        rel_worktree = worktree  # another drive on Windows: Node's relative() returns the absolute path too
    entry.update({
        "worktree": rel_worktree if rel_worktree != "" else ".", "branch": branch,
        "specs": [s.replace("\\", "/") for s in specs],
        "workbench_commit": commit, "approved_by": approver, "approved_at": date,
        "spec_sha256": spec_hash(plan), "tasks": len(acs),
        "amendments": (prior.get("amendments") or 0) + (1 if amend else 0),
    })
    lanes[lane] = entry
    _write_text(rec_path, _REC_HEADER + json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    print(f"{'amended' if amend else 'wrote'} {plan_path}: {len(acs)} task row(s), Status: approved, "
          f"Branch: {branch}, approved @ workbench {commit} by {approver}" +
          (f" — {added} row(s) added, {removed} dropped" if amend else "") + f"\nrecorded in {rec_path}")
    return 0


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == "archive":
        return _archive(argv[1:])
    return _write_plan(argv)


if __name__ == "__main__":
    sys.exit(main())
