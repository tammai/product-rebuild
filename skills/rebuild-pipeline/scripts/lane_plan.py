#!/usr/bin/env python3
"""lane_plan.py — write a G5 build lane's sdlc record from the slice specs you approved (2.0.0).
Run from the workbench root, right after the slice's specs are approved and before the lane
is dispatched.

  python3 scripts/lane_plan.py S3 billing-backend --worktree ../app-S3-billing \\
       --specs plan/specs/S3/billing.md,plan/specs/S3/invoicing.md [--risk high] [--track L]
  python3 scripts/lane_plan.py S3 billing-backend --worktree ../app-S3-billing \\
       --specs plan/specs/S3/billing.md --amend --reason "AC 4 contradicted R-BILL-002"
  python3 scripts/lane_plan.py archive S3 billing-backend     # slice end: record copied to the workbench

WHAT IT WRITES. A lane is one sdlc feature in its worktree (specs/Spec Wrap sdlc instead of
porting it.md). This script writes that feature's record at the moment you approve the specs:
  - the change file, `<docs_dir>/changes/<feature>.md`: `## Why` names the approved specs, the
    workbench commit and the approver; one `AC-nnn` per spec criterion, verbatim, `rule_id`
    included; an `## Acceptance tests` table whose Test and Run cells say `TBD`;
  - the state file, through sdlc's own `state.py new`, then `state.py advance <f> 4` with the
    approval in the Gate log (APPROVAL_NOTE below). The feature starts at sdlc's Build.
The lane then fills in the HOW, which an approved spec does not name: each task's files (written
`TBD` here, because state.py requires a value), the Public Surface, and the Test and Run cells. sdlc's Define writes those by hand too. The WHAT, the
criteria, is fixed here, hashed into plan/lane-plans/<Sn>.yaml, and changes only through
`--amend`.

WHY A SCRIPT. The approval has to be written by something that is not the lane: a lane told to
write its own record would be approving itself. The spec gate (hooks/scripts/spec_gate_guard.py)
allows no non-trivial edit in a lane worktree until an active sdlc feature there carries the
approval line for that worktree's branch. A doc can only ask the lane to behave; this writes the
line the gate reads.

THE FORMAT THE GATE READS: the Gate log note starts `rebuild-approval: branch <branch>;`, and an
open question starting `amend:` freezes the lane (the lane raises it with `state.py blocker
raise "amend: ..."` when it finds the spec wrong). These are hooklib's APPROVAL_NOTE and
AMEND_PREFIX. This script is vendored into each workbench and runs alone, so it carries its own
copy; eval/lane_plan.py imports both sides and fails if they stop agreeing. If you change one,
change both.

FINDING SDLC. `state.py` is sdlc's, so this script needs sdlc's install folder: `--sdlc-root`, else
$SDLC_PLUGIN_ROOT, else the newest `sdlc@sdlc` in `installed_plugins.json` under $CLAUDE_CONFIG_DIR
or ~/.claude. The plugin depends on sdlc, so an install without one cannot load the pipeline.

It refuses rather than guesses: specs with uncommitted changes (the approval would point at text
no commit holds), a worktree on a branch other than slice/<Sn>-<lane>, a repo sdlc has not set up,
and a lane whose record is open (use --amend). It never commits in the code repo: `state.py new`
records `Base:` as HEAD at that moment, and a commit rewritten after it leaves Base pointing at a
commit that no longer exists (the 2026-11-03 lane spike did exactly that).
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` silently matches nothing. Same helper in every
# script that parses text; copied, not imported, because each is vendored and must run alone.
def _read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


# Written with newline="\n" so the hash of `## Acceptance criteria` is taken over LF text everywhere.
def _write_text(p, text):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# The spec gate's own format, copied from hooks/scripts/hooklib.py (APPROVAL_NOTE, AMEND_PREFIX).
# Not imported: this script is vendored into workbenches. eval/lane_plan.py fails if they diverge.
APPROVAL_NOTE = re.compile(r"rebuild-approval: branch (\S+);")
AMEND_PREFIX = "amend:"


def _trim(s):
    return s.strip()


def _ac_section(change):
    m = re.search(r"^## Acceptance criteria\n([\s\S]*?)(?=^## )", change, re.M)
    return m.group(1) if m else None


def ac_hash(change):
    """sha256 of the change file's `## Acceptance criteria` section: what was approved."""
    s = _ac_section(change)
    return None if s is None else hashlib.sha256(s.encode("utf-8")).hexdigest()


def _ac_items(change):
    """[(id, text)] from a change file this script wrote."""
    return re.findall(r"^- \*\*(AC-\d{3})\*\* — (.*)$", _ac_section(change) or "", re.M)


def _test_rows(change):
    """{AC id: (test, run)} from the `## Acceptance tests` table."""
    m = re.search(r"^## Acceptance tests\n([\s\S]*?)(?=^## |\Z)", change, re.M)
    rows = {}
    for line in (m.group(1) if m else "").split("\n"):
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(cells) == 3 and re.fullmatch(r"AC-\d{3}", cells[0]):
            rows[cells[0]] = (cells[1], cells[2])
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


def _field(text, name):
    m = re.search(rf"^{re.escape(name)}:[ \t]*(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def _section_items(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\n([\s\S]*?)(?=^## |\Z)", text, re.M)
    return [l[2:].strip() for l in (m.group(1) if m else "").split("\n") if l.startswith("- ") and l[2:].strip()]


def lane_state(lrec, root="."):
    """What slice_review.py reports for one lane: read from its sdlc record, or from the copy
    `archive` took. {status, stage, acs, tested, amending, ac_edited, source} or {missing: reason}."""
    arch = lrec.get("archived")
    if arch:
        change_p = os.path.join(root, arch["change"])
        state_p = os.path.join(root, arch["state"])
        source = "archive"
    else:
        change_p = os.path.join(root, lrec["worktree"], lrec["change"])
        state_p = os.path.join(root, lrec["worktree"], lrec["state"])
        source = "worktree"
    if not (os.path.exists(change_p) and os.path.exists(state_p)):
        return {"missing": f"no sdlc record at `{change_p}` / `{state_p}`"}
    change, state = _read_text(change_p), _read_text(state_p)
    rows = _test_rows(change)
    cur = re.search(r"^Current:\s*Stage\s+(\d+)", state, re.M)
    return {
        "status": _field(state, "Status") or "(none)", "stage": int(cur.group(1)) if cur else None,
        "acs": len(_ac_items(change)),
        "tested": len([1 for t, _ in rows.values() if t and t != "TBD"]),
        "amending": any(q.startswith(AMEND_PREFIX) for q in _section_items(state, "Open questions")),
        "ac_edited": ac_hash(change) != lrec.get("ac_sha256"), "source": source,
    }


_REC_HEADER = "# Written by scripts/lane_plan.py; read by slice_review.py. Do not hand-edit.\n"


def _iso_now():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _local_date():
    return datetime.now().strftime("%Y-%m-%d")


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


# git's stderr is left attached to ours, so a refused `ls-files --error-unmatch` shows git's reason.
def _git(cwd, *a):
    r = subprocess.run(["git", "-C", cwd, *a], stdout=subprocess.PIPE, text=True, encoding="utf-8", check=True)
    return _trim(r.stdout)


# The acceptance criteria of one spec: the list items under `## Acceptance criteria`, the same
# section and item shape validate.py counts for its rule_id figures, numbered heading
# (`## 5. Acceptance criteria`) included. Change the heading pattern in both together.
# The heading line itself is skipped: `5. Acceptance criteria` matches the list-item pattern.
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


def sdlc_root(args):
    """sdlc's install folder (the one holding scripts/state.py), or None."""
    for cand in (_opt(args, "--sdlc-root"), os.environ.get("SDLC_PLUGIN_ROOT")):
        if cand:
            return cand if os.path.exists(os.path.join(cand, "scripts", "state.py")) else None
    best = None
    for cfg in (os.environ.get("CLAUDE_CONFIG_DIR"), os.path.join(os.path.expanduser("~"), ".claude")):
        p = os.path.join(cfg, "plugins", "installed_plugins.json") if cfg else None
        if not p or not os.path.exists(p):
            continue
        try:
            entries = json.loads(_read_text(p)).get("plugins", {}).get("sdlc@sdlc") or []
        except (ValueError, AttributeError):
            continue
        for e in entries:
            path = (e or {}).get("installPath")
            if not path or not os.path.exists(os.path.join(path, "scripts", "state.py")):
                continue
            ver = tuple(int(x) for x in re.findall(r"\d+", str(e.get("version") or "0"))[:3])
            if best is None or ver > best[0]:
                best = (ver, path)
    return best[1] if best else None


def _state_py(sdlc, worktree, *a):
    """Run sdlc's state.py in the worktree; its stdout is one JSON object."""
    r = subprocess.run([sys.executable, os.path.join(sdlc, "scripts", "state.py"), "--root", worktree, *a],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except ValueError:
        out = {}
    if r.returncode != 0 or not out.get("ok"):
        raise RuntimeError(out.get("error") or r.stderr.strip() or r.stdout.strip() or f"exit {r.returncode}")
    return out


def _state_files(worktree, feature):
    """Every file state.py writes for a feature: the state file and its git-ignored control contract."""
    d = os.path.join(worktree, ".sdlc", "state")
    return [os.path.join(d, n) for n in (f"{feature}.md", f"{feature}.json", f"{feature}.events.jsonl")
            if os.path.exists(os.path.join(d, n))]


def _docs_dir(worktree):
    """sdlc's docs folder for this repo, or None when sdlc has not set it up."""
    p = os.path.join(worktree, ".sdlc", "config.json")
    if not os.path.exists(p):
        return None
    try:
        d = json.loads(_read_text(p)).get("docs_dir")
    except (ValueError, AttributeError):
        return None
    return d if isinstance(d, str) and d and not d.startswith(("/", "..")) else "docs/sdlc"


def _change_text(slice_id, lane, branch, specs, commit, approver, date, acs, tests, amendments):
    """acs: [(id, module, criterion)]; tests: {id: (test, run)}."""
    approved = ", ".join(f"`{s}`" for s in specs)
    rows = [f"| {i} | {tests.get(i, ('TBD', '`TBD`'))[0]} | {tests.get(i, ('TBD', '`TBD`'))[1]} |" for i, _, _ in acs]
    # The title is a Conventional subject on purpose: sdlc's ship.py makes it the commit subject, and the
    # repo's commit-msg hook and this plugin's commit gate refuse any other (the 2026-11-03 e2e run's
    # "S1 pricing: rebuild build lane" would have been refused in a real rebuild repo).
    return "\n".join([
        f"# feat({lane}): rebuild slice {slice_id}",
        "",
        "## Why",
        "",
        f"**Request (verbatim):** Build lane {slice_id} `{lane}` of the rebuild against its approved specs.",
        "",
        f"Approved specs: {approved} at workbench commit `{commit}`, approved by {approver} on {date}; branch `{branch}`. "
        "The specs are the source and this file is their index plus the tests. It was written by the rebuild "
        "pipeline's `lane_plan.py`: fill in only the Test and Run cells below. A criterion changes only through "
        "`lane_plan.py --amend`; when one is wrong, raise `state.py blocker \"amend: <what and why>\"` and report.",
        "",
        "## Acceptance criteria",
        "",
        *[f"- **{i}** — `{mod}`: {crit}" for i, mod, crit in acs],
        "",
        "## Acceptance tests",
        "",
        "| AC | Test | Run |",
        "|---|---|---|",
        *rows,
        "",
        "## Must never break",
        "",
        "- Each criterion's behaviour exactly as its approved spec states it: a disagreement is an amendment, never a quiet change.",
        "",
        "## Out of scope",
        "",
        "- Anything the approved specs do not ask for.",
        *(["", "## Amendments", "", *amendments] if amendments else []),
        "",
    ])


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
        return die(f"no record for {slice_id} {lane}.")
    if lrec.get("archived"):
        return die(f"{slice_id} {lane} was already archived to {lrec['archived'].get('change')}.")
    st = lane_state(lrec)
    if st.get("missing"):
        return die(st["missing"] + ".")
    # Archiving is the claim that the lane is finished: sdlc's ship.py sets `Status: done` once
    # verify, the review the table fired and the commit are through. Anything else is still open.
    if st["status"] != "done":
        return die(f"the lane's sdlc feature is Status: {st['status']} (Stage {st['stage']}). "
                   "Only a lane sdlc shipped (Status: done) is archived.")
    dest_dir = os.path.join("plan", "lane-plans", "archive", f"{slice_id}-{lane}")
    copies = {}
    for key in ("change", "state"):
        src = os.path.join(lrec["worktree"], lrec[key])
        dst = os.path.join(dest_dir, os.path.basename(src))
        _write_text(dst, _read_text(src))
        copies[key] = dst.replace("\\", "/")
    lrec["archived"] = {**copies, "at": _iso_now(), "ac_edited": st["ac_edited"]}
    _save_record(slice_id, rec)
    print(f"{slice_id} {lane}: sdlc feature {lrec['feature']} done, record copied to {dest_dir}" +
          (" — WARNING: its acceptance criteria differ from what was approved; slice-review will name it."
           if st["ac_edited"] else ""))
    return 0


def _write_record(args):
    def die(msg):
        return _die("lane-plan", msg)
    value_flags = ("--worktree", "--specs", "--reason", "--branch", "--sdlc-root", "--risk", "--track")
    slice_id, lane = (_positionals(args, value_flags) + [None, None])[:2]
    amend = "--amend" in args

    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        return die("no locks/pipeline.yaml here — run from the workbench root.")
    if not slice_id or not lane or not _opt(args, "--worktree") or not _opt(args, "--specs"):
        return die('usage: lane_plan.py <Sn> <lane> --worktree <path> --specs <a.md,b.md> [--risk low|high] '
                   '[--track M|L] [--amend --reason "..."] [--branch <name>] [--sdlc-root <dir>]')
    if amend and not _opt(args, "--reason"):
        return die("--amend needs --reason: the amendment log is the only record the approved criteria changed.")
    risk = _opt(args, "--risk") or "low"
    track = (_opt(args, "--track") or "M").upper()
    if risk not in ("low", "high") or track not in ("M", "L"):
        return die("--risk is low or high, --track is M or L.")
    # sdlc refuses a feature name that is not lowercase letters, digits and dashes.
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", lane) or not re.fullmatch(r"S\d+", slice_id):
        return die("the slice is S<n> and the lane is lowercase letters, digits and dashes (sdlc names features that way).")

    worktree = os.path.abspath(_opt(args, "--worktree"))
    specs = [s.replace("\\", "/") for s in (_trim(s) for s in _opt(args, "--specs").split(",")) if s]

    # The approval must point at committed text.
    for s in specs:
        if not os.path.exists(s):
            return die(f"no such spec {s}")
        if not s.startswith(f"plan/specs/{slice_id}/"):
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
        approver = ""
    if not approver:
        return die("git user.name is unset in the workbench, so the approval would name nobody.")

    try:
        branch = _git(worktree, "branch", "--show-current")
    except (subprocess.CalledProcessError, OSError):
        return die(f"{worktree} is not a git worktree.")
    expected = _opt(args, "--branch") or f"slice/{slice_id}-{lane}"
    if branch != expected:
        return die(f"{worktree} is on '{branch or '(detached)'}', expected '{expected}'. One lane, one worktree, one "
                   f"branch: the spec gate reads the approval per branch.")
    docs = _docs_dir(worktree)
    if not docs:
        return die(f"{worktree} has no .sdlc/config.json: the code repo is not set up for sdlc. "
                   "Set it up first (g5-first-slice.md, step 0), then cut the lane's worktree.")
    sdlc = sdlc_root(args)
    if not sdlc:
        return die("sdlc's install folder was not found (needs scripts/state.py). Pass --sdlc-root <dir> "
                   "or set SDLC_PLUGIN_ROOT; `claude plugin list` shows whether sdlc@sdlc is installed.")

    rec = read_lane_plans(slice_id) or {"slice": slice_id, "lanes": {}}
    lanes = rec.setdefault("lanes", {})
    prior = lanes.get(lane) or {}
    if prior and not prior.get("archived") and not amend:
        return die(f"{slice_id} {lane} already has an open sdlc feature ({prior.get('feature')}). "
                   "Use --amend if the approved specs changed, or archive it once sdlc has shipped it.")
    if amend and (not prior or prior.get("archived")):
        return die(f"--amend: {slice_id} {lane} has no open record to amend.")

    criteria = []
    for s in specs:
        mod = re.sub(r"\.md\Z", "", s.split("/")[-1])
        for crit in _acceptance_criteria(_read_text(s)):
            criteria.append((mod, crit))
    if not criteria:
        return die("the specs carry no `## Acceptance criteria` items, so there are no criteria to approve.")
    if len(criteria) > 999:
        return die("more than 999 criteria: sdlc numbers them AC-001 to AC-999. Split the lane.")

    date = _local_date()
    note_specs = ", ".join(specs)
    if amend:
        # Ids stay stable: an unchanged criterion keeps its id and its Test/Run cells (and so its red
        # record in verify.py); a changed or new one takes the next unused id and starts at TBD.
        change_p = os.path.join(worktree, prior["change"])
        old = _read_text(change_p)
        old_items = _ac_items(old)
        by_text = {t: i for i, t in old_items}
        old_tests = _test_rows(old)
        used = {int(i[3:]) for i, _ in old_items}
        nxt = max(used or {0}) + 1
        acs, tests, added = [], {}, 0
        for mod, crit in criteria:
            text = f"`{mod}`: {crit}"
            if text in by_text:
                i = by_text.pop(text)
                tests[i] = old_tests.get(i, ("TBD", "`TBD`"))
            else:
                i, nxt, added = f"AC-{nxt:03d}", nxt + 1, added + 1
            acs.append((i, mod, crit))
        dropped = len(by_text)
        am = re.search(r"^## Amendments\n\n([\s\S]*?)\n*\Z", old, re.M)
        amendments = [l for l in (am.group(1).split("\n") if am else []) if l.strip()]
        amendments.append(f"- {date} @ workbench {commit}, {approver}: {_opt(args, '--reason')} "
                          f"(criteria added {added}, dropped {dropped})")
        _write_text(change_p, _change_text(slice_id, lane, branch, specs, commit, approver, date, acs, tests, amendments))
        feature = prior["feature"]
        try:
            _state_py(sdlc, worktree, "log", feature,
                      f"rebuild-approval: branch {branch}; amended: {note_specs} @ workbench {commit}; "
                      f"approved by {approver}; reason: {_opt(args, '--reason')}")
            state_text = _read_text(os.path.join(worktree, prior["state"]))
            for q in _section_items(state_text, "Open questions"):
                if q.startswith(AMEND_PREFIX):
                    _state_py(sdlc, worktree, "blocker", feature, "resolve", q)
        except RuntimeError as e:
            return die(f"sdlc's state.py refused: {e}")
        state_rel, change_rel = prior["state"], prior["change"]
    else:
        feature = f"{datetime.now().strftime('%Y-%m-%d')}-{track.lower()}-{slice_id.lower()}-{lane}"
        change_rel = f"{docs}/changes/{feature}.md"
        if os.path.exists(os.path.join(worktree, change_rel)):
            return die(f"{change_rel} already exists in {worktree}: a record this script did not track.")
        acs = [(f"AC-{n + 1:03d}", mod, crit) for n, (mod, crit) in enumerate(criteria)]
        _write_text(os.path.join(worktree, change_rel),
                    _change_text(slice_id, lane, branch, specs, commit, approver, date, acs, {}, []))
        tasks = []
        for s in specs:
            mod = re.sub(r"\.md\Z", "", s.split("/")[-1])
            ids = " ".join(i for i, m, _ in acs if m == mod)
            tasks += ["--task", f"{mod} | {ids} | TBD"]
        try:
            out = _state_py(sdlc, worktree, "new", feature, "--track", track, "--risk", risk,
                            "--footprint", "0", "--build", "inline: this lane, one subagent; the orchestrator runs Review",
                            "--handoff", f"approved specs: {note_specs} (workbench {commit})", *tasks)
            _state_py(sdlc, worktree, "advance", feature, "4", "--gate", "pass", "--note",
                      f"rebuild-approval: branch {branch}; specs {note_specs} @ workbench {commit}; "
                      f"approved by {approver} (lane_plan.py)")
        except RuntimeError as e:
            # Leave nothing half-made behind: a change file with no state, or a state never advanced
            # to Build, would read as a lane nobody approved.
            for p in [os.path.join(worktree, change_rel)] + _state_files(worktree, feature):
                try:
                    os.unlink(p)
                except OSError:
                    pass
            return die(f"sdlc's state.py refused: {e}. Nothing was left in the worktree.")
        state_rel = (out.get("event") or {}).get("state") or f".sdlc/state/{feature}.md"

    change = _read_text(os.path.join(worktree, change_rel))
    try:
        rel_worktree = os.path.relpath(worktree, ".")
    except ValueError:
        rel_worktree = worktree  # another drive on Windows
    lanes[lane] = {
        "worktree": rel_worktree, "branch": branch, "feature": feature,
        "change": change_rel, "state": state_rel, "specs": specs,
        "spec_sha256": {s: hashlib.sha256(_read_text(s).encode("utf-8")).hexdigest() for s in specs},
        "workbench_commit": commit, "approved_by": approver, "approved_at": date,
        "ac_sha256": ac_hash(change), "criteria": len(acs),
        "amendments": (prior.get("amendments") or 0) + (1 if amend else 0),
    }
    _save_record(slice_id, rec)
    print(f"{'amended' if amend else 'wrote'} sdlc feature {feature} in {worktree}: {len(acs)} criteria, at Build, "
          f"approved @ workbench {commit} by {approver} for branch {branch}\n"
          f"  change file: {change_rel}\n  state file:  {state_rel}\n  sdlc:        {sdlc}\n"
          f"recorded in plan/lane-plans/{slice_id}.yaml")
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
    return _write_record(argv)


if __name__ == "__main__":
    sys.exit(main())
