#!/usr/bin/env python3
"""lane_plan.py — open a G5 build lane as an sdlc feature from rspec's criteria (05 P5). Run from the workbench
root, once the slice passes step 0 and before the lane is dispatched.

  python3 scripts/lane_plan.py step0 S3                       # every criterion has a level 2 test or rspec's reason
  python3 scripts/lane_plan.py S3 billing --worktree ../app-S3-billing --features F-BIL-01,F-BIL-02 \\
       --approved-by "Ada Lovelace" [--risk high]
  python3 scripts/lane_plan.py S3 fix-r1-bil --worktree ../app-S3-fix --fix 1 --findings BH-0003,BH-0007
  python3 scripts/lane_plan.py questions S3                   # batch the lanes' spec questions for rspec:amend
  python3 scripts/lane_plan.py refresh S3 billing             # re-copy the lock and open tests after an amend
  python3 scripts/lane_plan.py archive S3 billing             # slice end: record copied to the workbench

WHAT IT WRITES. A lane is one sdlc feature in its worktree, in sdlc's spec-backed mode: a change file whose
ACs cite the criterion IDs, the state file through sdlc's own `state.py new --criteria` and `state.py advance`
to Build with the approval in the Gate log (APPROVAL_NOTE below), and in the code repo the lane's open tests and
a lock copy (see "3.0.0: lanes from rspec's slices" below). The lane fills in the HOW: each task's files, the
Public Surface, and the Test and Run cells. A wrong criterion is a spec question (sdlc's `state.py question`),
answered by rspec:amend; nothing here edits a criterion.

WHY A SCRIPT. The approval has to be written by something that is not the lane: a lane told to write its own
record would be approving itself. The spec gate (hooks/scripts/spec_gate_guard.py) allows no non-trivial edit in
a lane worktree until an active sdlc feature there carries the approval line for that worktree's branch.

THE FORMAT THE GATE READS: the Gate log note starts `rebuild-approval: branch <branch>;`, and an open question
starting `amend:` freezes the lane. Those are hooklib's APPROVAL_NOTE and AMEND_PREFIX. This script is vendored into each workbench and runs alone, so it carries its own copy;
eval/lane_plan.py imports both sides and fails if they stop agreeing. If you change one, change both.

FINDING SDLC. `state.py` is sdlc's, so this script needs sdlc's install folder: `--sdlc-root`, else
$SDLC_PLUGIN_ROOT, else the newest `sdlc@sdlc` in `installed_plugins.json` under $CLAUDE_CONFIG_DIR or ~/.claude.
Build's stage number is read from the state file the installed sdlc just wrote (stage_numbers()), never assumed.

It refuses rather than guesses: a worktree on a branch other than slice/<Sn>-<lane>, a repo sdlc has not set up,
a lane whose record is open, a slice that fails step 0, a lane beyond the slice's lane cap. It never commits in
the code repo: `state.py new` records `Base:` as HEAD at that moment, and a commit rewritten after it leaves Base
pointing at a commit that no longer exists.
"""

import hashlib
import json
import os
import re
import shutil
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
    return re.findall(r"^- \*\*(AC-\d{3})\*\* (?:—|→) (.*)$", _ac_section(change) or "", re.M)


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
    return [l[2:].strip() for l in _section_lines(text, heading) if l.startswith("- ") and l[2:].strip()]


# sdlc 2.x's numbering, for a state file whose Stages checklist can't be read. Only `Process: 2` means
# 2.x; any other marker gets no guess, because a wrong Build number moves a lane into Ship.
SDLC2_STAGES = {"Define": 1, "Build": 4, "Review": 5, "Ship": 8}


def stage_numbers(state):
    """{phase name: stage number} as the sdlc that wrote this state file numbers them, or None.
    Read from its `## Stages` checklist (`- [ ] 2 Build`), which state.py writes for tracks M and L
    (the only ones a lane uses) from its own constants, so the answer always matches the installed
    sdlc, whichever version it is. Falls back to the 2.x numbers on `Process: 2`."""
    found = {m.group(2): int(m.group(1)) for m in re.finditer(r"^- \[[ x]\] (\d+) (\w+)", "\n".join(
        _section_lines(state, "Stages")), re.M)}
    if "Build" in found:
        return found
    return dict(SDLC2_STAGES) if re.search(r"^Process:\s*2\b", state, re.M) else None


def current_phase(state):
    """(stage number, phase name) from `Current: Stage <n> – <Name>`, either part None if unreadable."""
    m = re.search(r"^Current:\s*Stage\s+(\d+)(?:\s*[–-]\s*(\w+))?", state, re.M)
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def _section_lines(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\n([\s\S]*?)(?=^## |\Z)", text, re.M)
    return (m.group(1) if m else "").split("\n")


def lane_state(lrec, root="."):
    """What slice_review.py reports for one lane: read from its sdlc record, or from the copy
    `archive` took. {status, stage, phase, acs, tested, amending, ac_edited, source} or {missing: reason}."""
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
    stage, phase = current_phase(state)
    return {
        "status": _field(state, "Status") or "(none)", "stage": stage, "phase": phase,
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


def sdlc_version(sdlc):
    """The version in the sdlc install's plugin.json (at its root or in .claude-plugin/), or "unknown"."""
    for rel in ("plugin.json", os.path.join(".claude-plugin", "plugin.json")):
        try:
            v = json.loads(_read_text(os.path.join(sdlc, rel))).get("version")
        except (OSError, ValueError, AttributeError):
            continue
        if v:
            return str(v)
    return "unknown"


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


# sdlc's change template ends in `## Review`, which its Review fills in once and keeps last. The file
# this script writes had none, so the orchestrator appended it by hand at the Kutt rebuild's first
# Ship (2026-11-03). Written empty here; an amendment keeps whatever Review already wrote.
REVIEW_PLACEHOLDER = ["## Review", "",
                      "<!-- Written once, in sdlc's Review, by the orchestrator (G5 step 4b). Keep it last. -->"]


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
        return die(f"the lane's sdlc feature is Status: {st['status']} (Stage {st['stage']} – {st['phase']}). "
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


# ---------------------------------------------------------------- 3.0.0: lanes from rspec's slices (05 P5)
#
# In 3.0 rspec writes the criteria and records the tests, in the workbench (`docs/`). sdlc 3.5 builds
# spec-backed only from what is inside the code repo: config `spec_lock` (a path in the repo, whose
# `spec` it resolves against the repo) and `acceptance/manifest.json`. The code repo holds the
# workbench as a submodule, so this copies, per lane: the lane's OPEN tests, byte-identical and each
# checked against the workbench manifest's sha256, with a manifest of only those entries; and the lock,
# its `spec` rewritten to the submodule's `docs`. Hidden tests never reach a lane by construction: they
# are not in the workbench bundle any more, and the lock copy names no test for them.

SPEC = "docs"
SPEC_BUNDLE = os.path.join(SPEC, "acceptance")
HOLDOUT_RECORD = os.path.join("plan", "holdout.json")  # holdout.RECORD; change both together
SPEC_LOCK = os.path.join(SPEC, "criteria.lock.json")
LANE_LOCK = ".rebuild/criteria.lock.json"  # in the lane worktree; config spec_lock names it
SLICE_RE = re.compile(r"^##\s*Slice\s+(\d+)\s*:?\s*(.*)$", re.M)  # rspec_lib.SLICE_RE; change both together
# rspec verify outcomes that leave a criterion at level 1 for a recorded reason (rspec verify_report.OUTCOMES).
LEVEL1_REASONS = ("unrecordable", "unseedable", "read-only reference")
DEFAULT_LANE_CAP = 3  # 05 P5 step 2, until G0 budgets say otherwise (rebuild.yaml budgets.parallel_lanes)


def _json(p):
    with open(p, encoding="utf-8") as fh:
        return json.loads(fh.read())


def slice_features():
    """{"S<n>": [feature IDs]} from rspec's build-plan.md, read as rspec's build_slices reads it."""
    p = os.path.join(SPEC, "build-plan.md")
    text = _read_text(p) if os.path.exists(p) else ""
    heads = list(SLICE_RE.finditer(text))
    out = {}
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        out[f"S{h.group(1)}"] = list(dict.fromkeys(re.findall(r"\bF-[A-Z][A-Z0-9]*-\d+\b", body)))
    return out


def _slice_rows(slice_id):
    feats = set(slice_features().get(slice_id) or [])
    return [c for c in (_json(SPEC_LOCK).get("criteria") or []) if c.get("feature") in feats and c.get("priority") != "Drop"]


def step0_missing(slice_id):
    """Criteria of the slice with neither a level 2 test in the bundle nor rspec's recorded reason (P5 step 0)."""
    tested = {t["criterion"] for t in (_json(os.path.join(SPEC_BUNDLE, "manifest.json")).get("tests") or [])}
    reasons = set()
    p = os.path.join(SPEC, "verify", "outcomes.jsonl")
    for line in (_read_text(p).splitlines() if os.path.exists(p) else []):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if isinstance(o, dict) and o.get("outcome") in LEVEL1_REASONS:
            reasons.add(o.get("criterion"))
    return [c for c in _slice_rows(slice_id) if not (c.get("level") == 2 and c["id"] in tested) and c["id"] not in reasons]


def _step0(args):
    slice_id = args[0] if args else None
    if not slice_id or not re.fullmatch(r"S\d+", slice_id):
        return _die("lane-plan", "usage: lane_plan.py step0 <Sn>")
    # Without the hidden entries a re-verify dropped, step 0 would send rspec:verify to re-record exactly the
    # hidden criteria as open tests.
    import holdout
    _changed, err = holdout.reconcile()
    if err:
        return _die("lane-plan", err)
    try:
        missing = step0_missing(slice_id)
    except (OSError, ValueError) as e:
        return _die("lane-plan", f"{slice_id} step 0 cannot run: {e}. rspec:check writes criteria.lock.json and the manifest.")
    if not missing:
        print(f"{slice_id} step 0: every criterion has a level 2 test or rspec's reason for staying at level 1.")
        return 0
    feats = ",".join(dict.fromkeys(c["feature"] for c in missing))
    print(f"{slice_id} step 0: {len(missing)} criteria have no level 2 test and no recorded reason:\n" +
          "\n".join(f"  {c['id']} (level {c.get('level')})" for c in missing) +
          f"\nRun rspec:verify --only {feats}, then step 0 again.", file=sys.stderr)
    return 1


def lane_cap():
    p = "rebuild.yaml"
    block = re.search(r"^budgets:[ \t]*\n((?:(?:[ \t]+.*)?\n)*)", _read_text(p) + "\n", re.M) if os.path.exists(p) else None
    m = block and re.search(r"^[ \t]+parallel_lanes:[ \t]*(\d+)", block.group(1), re.M)
    return int(m.group(1)) if m else DEFAULT_LANE_CAP


def workbench_in(worktree, explicit=None):
    """The workbench submodule's path inside the code repo (posix), from .gitmodules, or None."""
    if explicit:
        return explicit.replace("\\", "/").strip("/")
    gm = os.path.join(worktree, ".gitmodules")
    if not os.path.exists(gm):
        return None
    name = os.path.basename(os.getcwd())
    for block in re.split(r"^\[submodule ", _read_text(gm), flags=re.M)[1:]:
        path = re.search(r"^\s*path\s*=\s*(.+)$", block, re.M)
        url = re.search(r"^\s*url\s*=\s*(.+)$", block, re.M)
        if not path:
            continue
        p = path.group(1).strip()
        u = re.sub(r"\.git\Z", "", (url.group(1).strip() if url else "").rstrip("/"))
        if u.replace("\\", "/").split("/")[-1] == name or os.path.exists(os.path.join(worktree, p, "locks", "pipeline.yaml")):
            return p.replace("\\", "/").strip("/")
    return None


def _sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def bundle_path(base, rel):
    """holdout.bundle_path, copied because this script runs alone; change the three together (holdout.py,
    boundary.py uses holdout's). None for a manifest path that is absolute, has a drive or `..`, or resolves
    outside `base`: an entry `../../p-holdout/...` would have this script copy a hidden test into a lane."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or re.match(r"^[a-zA-Z]:", rel) \
            or ".." in re.split(r"[\\/]+", rel):
        return None
    p = os.path.join(base, rel)
    real_base = os.path.realpath(base)
    real = os.path.realpath(p)
    return p if real == real_base or real.startswith(real_base.rstrip(os.sep) + os.sep) else None


def copy_to_lane(worktree, criteria, wb_path):
    """Write the lane's open bundle and lock copy, or return why not (nothing written then)."""
    manifest = _json(os.path.join(SPEC_BUNDLE, "manifest.json"))
    tests = manifest.get("tests") or []
    # The split's record, not the manifest's visibility, says what is hidden: the manifest is rebuilt by rspec.
    hidden = set(_json(HOLDOUT_RECORD).get("hidden") or []) if os.path.exists(HOLDOUT_RECORD) else set()
    mine = [t for t in tests if t.get("criterion") in criteria and t.get("criterion") not in hidden and t.get("visibility", "open") == "open"]
    dest = os.path.join(worktree, "acceptance")
    stray = [str(t.get("path")) for t in mine if not bundle_path(SPEC_BUNDLE, t.get("path")) or not bundle_path(dest, t.get("path"))]
    if stray:
        return f"these manifest paths leave the acceptance bundle, so nothing is copied: {', '.join(stray)}."
    bad = [f"{t['path']} (manifest {t.get('sha256', '?')[:12]}…)" for t in mine
           if not os.path.exists(os.path.join(SPEC_BUNDLE, t["path"])) or _sha(os.path.join(SPEC_BUNDLE, t["path"])) != t.get("sha256")]
    if bad:
        return ("these tests differ from the sha256 the workbench manifest records, so they are not copied: "
                + ", ".join(bad) + ". A recorded test changes only through rspec:amend.")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    for t in mine:
        out = os.path.join(dest, t["path"])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copyfile(os.path.join(SPEC_BUNDLE, t["path"]), out)
    if os.path.isdir(os.path.join(SPEC_BUNDLE, "seed")):
        shutil.copytree(os.path.join(SPEC_BUNDLE, "seed"), os.path.join(dest, "seed"))
    lane_manifest = dict(manifest, tests=mine)
    _write_text(os.path.join(dest, "manifest.json"), json.dumps(lane_manifest, indent=2, ensure_ascii=False) + "\n")
    lock = _json(SPEC_LOCK)
    open_ids = {t["criterion"] for t in tests if t.get("visibility", "open") == "open"}
    for c in lock.get("criteria") or []:
        if c.get("id") not in open_ids:
            c["test"] = None  # a hidden test's path is not the lane's to know
    lock["spec"] = f"{wb_path}/{SPEC}"
    _write_text(os.path.join(worktree, *LANE_LOCK.split("/")), json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    cfg_p = os.path.join(worktree, ".sdlc", "config.json")
    cfg = _json(cfg_p) if os.path.exists(cfg_p) else {}
    cfg["spec_lock"] = LANE_LOCK
    _write_text(cfg_p, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    return None, mine


def _cited_change(slice_id, lane, branch, features, commit, approver, date, ids, tests, why=None):
    """ids: criterion IDs to cite, or (finding id, text) for a finding with no criterion, which is restated."""
    rows = []
    by_crit = {t["criterion"]: t for t in tests}
    for n, cid in enumerate(ids, 1):
        t = by_crit.get(cid) if isinstance(cid, str) else None
        run = f"`contracts.py run-http acceptance/{t['path']}`" if t and t.get("runner") == "http" else "`TBD`"
        rows.append(f"| AC-{n:03d} | {'acceptance/' + t['path'] if t else 'TBD'} | {run} |")
    return "\n".join([
        f"# feat({lane}): rebuild slice {slice_id}",
        "",
        "## Why",
        "",
        f"**Request (verbatim):** Build lane {slice_id} `{lane}` of the rebuild against its rspec criteria.",
        "",
        why or f"Features {', '.join(features)} of slice {slice_id} (rspec build plan, Gate 2) at workbench commit `{commit}`, "
        f"approved by {approver} on {date}; branch `{branch}`. Each AC cites a criterion in the lock "
        f"(`{LANE_LOCK}`, copied from the workbench by the rebuild pipeline's `lane_plan.py`); its text is the "
        "lock's. Fill in only the Test and Run cells still `TBD`. When a criterion is ambiguous, wrong or untestable, "
        "ask: `state.py question <feature> <criterion> \"<question>\"`.",
        "",
        "## Acceptance criteria",
        "",
        *[f"- **AC-{n:03d}** → {cid}" if isinstance(cid, str) else f"- **AC-{n:03d}** — `{cid[0]}`: {cid[1]}"
          for n, cid in enumerate(ids, 1)],
        "",
        "## Acceptance tests",
        "",
        "| AC | Test | Run |",
        "|---|---|---|",
        *rows,
        "",
        "## Must never break",
        "",
        "- Each criterion's behaviour exactly as the lock states it: a disagreement is a spec question, never a quiet change.",
        "",
        "## Out of scope",
        "",
        "- Anything the cited criteria do not ask for.",
        "",
        *REVIEW_PLACEHOLDER,
        "",
    ])


def _write_rspec_lane(args):
    def die(msg):
        return _die("lane-plan", msg)
    value_flags = ("--worktree", "--features", "--branch", "--sdlc-root", "--risk", "--track", "--approved-by",
                   "--workbench-path", "--fix", "--findings")
    slice_id, lane = (_positionals(args, value_flags) + [None, None])[:2]
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        return die("no locks/pipeline.yaml here — run from the workbench root.")
    fix = _opt(args, "--fix")
    if not slice_id or not lane or not _opt(args, "--worktree") or not (_opt(args, "--features") or (fix and _opt(args, "--findings"))):
        return die("usage: lane_plan.py <Sn> <lane> --worktree <path> (--features F-A-01,F-B-02 | --fix <round> --findings <ids>) "
                   "[--approved-by <name>] [--risk low|high] [--track M|L] [--workbench-path <submodule path>] [--sdlc-root <dir>]")
    if "--amend" in args:
        return die("a lane built from rspec criteria is not amended here: answer its spec questions with rspec:amend, "
                   "then `lane_plan.py refresh <Sn> <lane>`.")
    risk, track = _opt(args, "--risk") or "low", (_opt(args, "--track") or "M").upper()
    if risk not in ("low", "high") or track not in ("M", "L"):
        return die("--risk is low or high, --track is M or L.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", lane) or not re.fullmatch(r"S\d+", slice_id):
        return die("the slice is S<n> and the lane is lowercase letters, digits and dashes (sdlc names features that way).")
    for p in (SPEC_LOCK, os.path.join(SPEC_BUNDLE, "manifest.json"), os.path.join(SPEC, "build-plan.md")):
        if not os.path.exists(p):
            return die(f"{p} is missing: rspec's handoff and check come first.")
    why = None
    if fix:
        # A fix lane (05 P6 routing): the findings route.py sent to sdlc in this round become its ACs. A finding
        # with a criterion cites it, so the lane gets that criterion's open test; one without is restated from
        # what the build did. A hidden finding cites its criterion only: its test never reaches a lane.
        want = [i.strip() for i in _opt(args, "--findings").split(",") if i.strip()]
        try:
            rounds = _json(os.path.join("plan", "fix-rounds", f"{slice_id}.json")).get("rounds") or []
        except (OSError, ValueError):
            rounds = []
        rnd = next((r for r in rounds if str(r.get("n")) == str(fix)), None)
        routed = {i for ids_ in ((rnd or {}).get("sdlc") or {}).values() for i in ids_}
        stray = [i for i in want if i not in routed]
        if stray:
            return die(f"round {fix} of {slice_id} did not route {', '.join(stray)} to sdlc (plan/fix-rounds/{slice_id}.json).")
        try:
            import route
            found = {f.get("id"): f for _, f, _h in route.findings(slice_id) if isinstance(f, dict)}
        except ImportError:
            return die("scripts/route.py is missing: the findings cannot be read.")
        acs, features = [], []
        for i in want:
            f = found.get(i) or {}
            crit = f.get("criterion")
            if crit and crit not in acs:
                acs.append(crit)
            elif not crit:
                acs.append((i, str((f.get("observed") or {}).get("rebuild", "")).replace("\n", " ")))
            feat = f.get("feature") or (crit.split(".")[0] if crit else None)
            if feat and feat not in features:
                features.append(feat)
        why = (f"Fix round {fix} of slice {slice_id}: findings {', '.join(want)} (plan/fix-rounds/{slice_id}-r{fix}.md), "
               f"routed by route.py. A cited criterion's text is the lock's (`{LANE_LOCK}`); a restated finding is what "
               "the build did that the reference does not. Fill in only the Test and Run cells still `TBD`.")
    else:
        features = [f.strip() for f in _opt(args, "--features").split(",") if f.strip()]
    in_slice = slice_features().get(slice_id) or []
    stray = [f for f in features if f not in in_slice]
    if stray:
        return die(f"not in {slice_id} of {SPEC}/build-plan.md: {', '.join(stray)}.")
    # The split checks this too, but it runs before Gate 4, when repos.yaml usually lists no code repo yet.
    import holdout
    exposed = holdout.exposure(holdout.holdout_dir())
    if exposed:
        return die(f"the holdout repo is reachable from a code repo: {'; '.join(exposed)}. Remove it there before "
                   f"opening a lane.")
    _changed, err = holdout.reconcile()  # an amend's re-verify may have dropped or re-opened hidden entries
    if err:
        return die(err)
    if not fix and step0_missing(slice_id):
        return die(f"{slice_id} fails step 0 (criteria with no level 2 test and no rspec reason): run "
                   f"`python3 scripts/lane_plan.py step0 {slice_id}` for the list, then rspec:verify --only <features>.")
    rec = read_lane_plans(slice_id) or {"slice": slice_id, "lanes": {}}
    lanes = rec.setdefault("lanes", {})
    prior = lanes.get(lane) or {}
    if prior and not prior.get("archived"):
        return die(f"{slice_id} {lane} already has an open sdlc feature ({prior.get('feature')}).")
    cap = lane_cap()
    open_lanes = [n for n, l in lanes.items() if n != lane and not l.get("archived")]
    if len(open_lanes) >= cap:
        return die(f"{slice_id} already has {len(open_lanes)} open lane(s) ({', '.join(open_lanes)}); the cap is {cap} "
                   f"(rebuild.yaml budgets.parallel_lanes). Archive one first, or raise the budget with the user.")
    if fix:
        ids = acs
    else:
        ids = [c["id"] for c in _json(SPEC_LOCK).get("criteria") or [] if c.get("feature") in features and c.get("priority") != "Drop"]
    if not ids:
        return die(f"the lock has no criteria for {', '.join(features)}.")
    cited = [i for i in ids if isinstance(i, str)]
    worktree = os.path.abspath(_opt(args, "--worktree"))
    try:
        branch = _git(worktree, "branch", "--show-current")
    except (subprocess.CalledProcessError, OSError):
        return die(f"{worktree} is not a git worktree.")
    expected = _opt(args, "--branch") or f"slice/{slice_id}-{lane}"
    if branch != expected:
        return die(f"{worktree} is on '{branch or '(detached)'}', expected '{expected}'.")
    docs = _docs_dir(worktree)
    if not docs:
        return die(f"{worktree} has no .sdlc/config.json: the code repo is not set up for sdlc.")
    wb_path = workbench_in(worktree, _opt(args, "--workbench-path"))
    if not wb_path:
        return die(f"cannot find the workbench submodule in {worktree}/.gitmodules: pass --workbench-path <path>.")
    sdlc = sdlc_root(args)
    if not sdlc:
        return die("sdlc's install folder was not found (needs scripts/state.py). Pass --sdlc-root <dir> or set SDLC_PLUGIN_ROOT.")
    try:
        commit = _git(".", "rev-parse", "--short", "HEAD")
    except (subprocess.CalledProcessError, OSError):
        return die("the workbench is not a git repository, so there is no commit for the approval to point at.")
    approver = (_opt(args, "--approved-by") or "").strip() or "(no --approved-by)"
    copied = copy_to_lane(worktree, set(cited), wb_path)
    if isinstance(copied, str):
        return die(copied)
    tests = copied[1]
    feature = f"{datetime.now().strftime('%Y-%m-%d')}-{track.lower()}-{slice_id.lower()}-{lane}"
    change_rel = f"{docs}/changes/{feature}.md"
    date = _local_date()
    _write_text(os.path.join(worktree, change_rel),
                _cited_change(slice_id, lane, branch, features, commit, approver, date, ids, tests, why))
    tasks = []
    groups = features or ["fix"]
    for f in groups:
        mine = [f"AC-{n:03d}" for n, cid in enumerate(ids, 1)
                if (cid.startswith(f + ".") if isinstance(cid, str) else f == groups[0])]
        tasks += ["--task", f"{f} | {' '.join(mine) or 'AC-001'} | TBD"]
    try:
        out = _state_py(sdlc, worktree, "new", feature, "--track", track, "--risk", risk, "--footprint", "0",
                        "--build", "inline: this lane, one subagent; the orchestrator runs Review",
                        "--handoff", f"rspec criteria of {', '.join(features)} (workbench {commit})", *tasks,
                        *(["--criteria", *cited] if cited else []))
        state_rel = (out.get("event") or {}).get("state") or f".sdlc/state/{feature}.md"
        build = (stage_numbers(_read_text(os.path.join(worktree, state_rel))) or {}).get("Build")
        if build is None:
            raise RuntimeError("could not read Build's stage number from the state file it wrote")
        _state_py(sdlc, worktree, "advance", feature, str(build), "--gate", "pass", "--note",
                  f"rebuild-approval: branch {branch}; rspec criteria {', '.join(features)} @ workbench {commit}; "
                  f"approved by {approver} (lane_plan.py)")
    except RuntimeError as e:
        for p in [os.path.join(worktree, change_rel)] + _state_files(worktree, feature):
            try:
                os.unlink(p)
            except OSError:
                pass
        return die(f"sdlc's state.py refused: {e}. The change and state files were removed; the lane's acceptance/ "
                   f"and {LANE_LOCK} copies stay (rerun replaces them).")
    try:
        rel_worktree = os.path.relpath(worktree, ".")
    except ValueError:
        rel_worktree = worktree
    lanes[lane] = {
        "worktree": rel_worktree, "branch": branch, "feature": feature, "change": change_rel, "state": state_rel,
        "features": features, "criteria_ids": cited, "fix_round": int(fix) if fix else None, "workbench_path": wb_path, "workbench_commit": commit,
        "approved_by": approver, "approved_at": date, "ac_sha256": ac_hash(_read_text(os.path.join(worktree, change_rel))),
        "criteria": len(ids), "amendments": 0, "sdlc_root": sdlc, "sdlc_version": sdlc_version(sdlc),
    }
    _save_record(slice_id, rec)
    print(f"wrote sdlc feature {feature} in {worktree}: {len(ids)} cited criteria, {len(tests)} open recorded tests, "
          f"at Build, approved @ workbench {commit} by {approver}\n  lock copy: {LANE_LOCK} (spec {wb_path}/{SPEC})\n"
          f"  sdlc: {sdlc} ({sdlc_version(sdlc)}): name it in the lane's brief\nrecorded in plan/lane-plans/{slice_id}.yaml")
    return 0


def _refresh(args):
    slice_id, lane = (args + [None, None])[:2]
    if not slice_id or not re.fullmatch(r"S\d+", slice_id):
        return _die("lane-plan", "usage: lane_plan.py refresh <Sn> <lane>")
    lrec = ((read_lane_plans(slice_id) or {}).get("lanes") or {}).get(lane or "")
    if not lrec or not lrec.get("criteria_ids"):
        return _die("lane-plan", f"no rspec lane {slice_id} {lane} in plan/lane-plans/{slice_id}.yaml.")
    # A refresh follows an amend, whose re-verify drops the hidden entries and may have re-recorded a hidden
    # test as open; reconcile first, so such a test is refused here instead of copied into the lane.
    import holdout
    changed, err = holdout.reconcile()
    if err:
        return _die("lane-plan", err)
    if changed:
        print(f"the hidden entries a re-verify dropped are back in {holdout.MANIFEST}; commit it and {holdout.RECORD}.")
    copied = copy_to_lane(lrec["worktree"], set(lrec["criteria_ids"]), lrec["workbench_path"])
    if isinstance(copied, str):
        return _die("lane-plan", copied)
    print(f"refreshed {slice_id} {lane}: {len(copied[1])} open tests and {LANE_LOCK}. In the lane, `state.py questions "
          f"<feature>` unblocks each question whose criterion the lock changed.")
    return 0


def _questions(args):
    slice_id = args[0] if args else None
    rec = read_lane_plans(slice_id) if slice_id and re.fullmatch(r"S\d+", slice_id) else None
    if not rec:
        return _die("lane-plan", "usage: lane_plan.py questions <Sn> (a slice with lanes)")
    rows = []
    for name, l in sorted((rec.get("lanes") or {}).items()):
        if l.get("archived"):
            continue
        d = os.path.join(l["worktree"], ".sdlc", ".work", "spec-questions")
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if f.endswith(".json"):
                try:
                    q = _json(os.path.join(d, f))
                except (OSError, ValueError):
                    q = {"criterion": "?", "question": f"(unreadable: {f})"}
                # Lane-written text goes into a file the orchestrator acts on: no cell may add a row or a line.
                cell = [str(x).replace("|", "/").replace("\r", " ").replace("\n", " ")
                        for x in (q.get("criterion", "?"), q.get("question", ""), f)]
                rows.append((cell[0], cell[1], name, cell[2]))
    lines = [f"# Spec questions, {slice_id}", "",
             "Batched for rspec:amend (human approval when an MVP criterion's `then` changes). After the amend and "
             "re-verify: `lane_plan.py refresh <Sn> <lane>`, then `state.py questions <feature>` in the lane.", "",
             "| Criterion | Question | Lane | File |", "|---|---|---|---|"]
    lines += [f"| {c} | {q} | {n} | {f} |" for c, q, n, f in rows]
    _write_text(os.path.join("plan", "spec-questions", f"{slice_id}.md"), "\n".join(lines) + "\n")
    print(f"{slice_id}: {len(rows)} spec question(s) -> plan/spec-questions/{slice_id}.md")
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
    if argv and argv[0] in ("step0", "refresh", "questions"):
        return {"step0": _step0, "refresh": _refresh, "questions": _questions}[argv[0]](argv[1:])
    return _write_rspec_lane(argv)


if __name__ == "__main__":
    sys.exit(main())
