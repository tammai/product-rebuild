#!/usr/bin/env python3
"""gate.py — view and manage gate locks. Run from the workbench root.
Usage:
  python3 scripts/gate.py status
  python3 scripts/gate.py lock <gate-id> [--by <name>]
  python3 scripts/gate.py lock gate-4 --accept-level2 "<reason>" --by <name>   # MVP level 2 below 90%
  python3 scripts/gate.py reopen <gate-id> --reason "..."
Locking records sha256 hashes of every file under the gate's `protects:` paths. Gates go in rspec's
order (1, 3, 2, 4, 5) and, from 3.0.0, lock rspec's artifacts in docs/; `status` also prints rspec's
own progress (its scripts/progress.py).

Standard library only, plus lazy imports of its siblings (playbook.py, sequence.py, gp.py, ...): lock files use a
fixed YAML subset written and parsed here, so `status` keeps answering on a workbench whose other
scripts are missing or broken. It is a script and not a line in a doc because the lock is the
pipeline's one irreversible act and the hashes must be computed the same way every time.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# Siblings are imported lazily inside `lock` and need the scripts directory on the path even
# when this file is imported rather than run.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

LOCKS = "locks"


# Every YAML/markdown file this script parses is read through here. With git's
# core.autocrlf=true (the Windows default) the working copy is CRLF, `^slices:\n` never
# matches, and `status` reported "0/18 slices done" on a workbench with eight done — a wrong
# phase, at the step the orchestration protocol trusts over its own memory. Same helper as
# playbook.py's _read_text; copied, not imported, because this file must run when others are
# missing (its siblings are imported lazily, inside the commands that need them).
def read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        return re.sub(r"\r\n?", "\n", fh.read())


def _join(*parts):
    return os.path.normpath(os.path.join(*parts))


def _undef(v):
    """A missing lock field printed as the word `undefined` in the Node twin; kept so output matches."""
    return "undefined" if v is None else v


# rspec's order, not the numbers' (05 P2): architecture (gate-3) is decided before the slices
# (gate-2) are cut, because rspec's handoff cuts them from the accepted ADRs and the verified
# criteria. The numbers stay as 2.x named them so existing locks, tags and docs stay readable.
ORDER = ["gate-1", "gate-3", "gate-2", "gate-4", "gate-5"]

# Where rspec keeps the spec in a workbench: its single-repo layout, `docs/` at the root.
SPEC = "docs"

# Paths a gate protects REGARDLESS of what its lock file's `protects:` list says, unioned in at
# lock time and written into the lock file (which hands them to gate-guard). `protects:` is
# written once at scaffold time, so this is how a path added by a later release reaches a
# workbench scaffolded earlier. gate-3's adr/ holds the vendored playbook and its scaffold manifest
# (the stack every code repo is created from); 3.0 release candidates scaffolded gate-3 without it.
REQUIRED_PROTECTS = {"gate-3": ["adr/"]}
PHASE_BEFORE = {
    "gate-1": "rspec init → discover → features (Gate 1 approves the feature list)",
    "gate-3": "rspec stories → tech (Gate 3: ADR approval, rspec handoff step 1)",
    "gate-2": "rspec audit → verify → handoff (Gate 2: the slices in build-plan.md)",
    "gate-4": "contracts and tests from rspec (Gate 4: openapi.json, schemas, criteria lock, acceptance bundle)",
    # NOT "GP production readiness" — see phase_before_gate5 below. Kept as the fallback for a
    # workbench with no slice plan at all.
    "gate-5": "GP production readiness",
}


def slice_states():
    """Slice states, for the one phase the gate sequence alone cannot name.

    G5 (build) and G6 (parity) sit BETWEEN gate-4 and gate-5 and are gated by neither, so deriving
    the phase from "first unlocked gate" reports GP production readiness the moment contracts lock —
    through every slice of the build, which is where a project spends most of its life. That is not
    a cosmetic slip: SKILL.md's orchestration protocol tells the model to trust this script's output
    over its memory of the conversation, so a wrong answer here is a wrong answer at the one step
    designed to catch stale assumptions.

    rspec's slices (docs/build-plan.md) in execution order, each with its plan/progress.yaml status,
    read through the vendored sibling sequence.py so this and the slice reports cannot disagree."""
    import sequence
    states = sequence.slice_statuses()
    return [{"id": sid, "status": states[sid]} for sid in sequence.read_sequence()["order"] if sid in states]


def rspec_root():
    """rspec's install folder (holding scripts/progress.py), or (None, why). $RSPEC_PLUGIN_ROOT
    wins, and a set value that is not an rspec install is not silently replaced by another one;
    else the newest rspec in Claude Code's installed_plugins.json. Same lookup lane_plan.py does
    for sdlc; copied, not imported, because each vendored script must run alone."""
    env = os.environ.get("RSPEC_PLUGIN_ROOT")
    if env:
        ok = os.path.exists(_join(env, "scripts", "progress.py"))
        return (env, None) if ok else (None, f"$RSPEC_PLUGIN_ROOT ({env}) has no scripts/progress.py")
    best = None
    for cfg in (os.environ.get("CLAUDE_CONFIG_DIR"), os.path.join(os.path.expanduser("~"), ".claude")):
        p = _join(cfg, "plugins", "installed_plugins.json") if cfg else None
        if not p or not os.path.exists(p):
            continue
        try:
            entries = json.loads(read_text(p)).get("plugins", {}).get("rspec@rspec") or []
        except (ValueError, AttributeError):
            continue
        for e in entries:
            path = (e or {}).get("installPath")
            if path and os.path.exists(_join(path, "scripts", "progress.py")):
                ver = tuple(int(x) for x in re.findall(r"\d+", str(e.get("version") or "0"))[:3])
                if best is None or ver > best[0]:
                    best = (ver, path)
    return (best[1], None) if best else (None, "rspec is not installed (no rspec@rspec in installed_plugins.json)")


def rspec_progress_line():
    """One line for `status`: rspec's own answer to where the spec stands (05 P2: read, never
    re-implemented). A check that cannot run says `not run: <reason>` (design rule 6)."""
    root, why = rspec_root()
    if not root:
        return f"rspec: not run: {why}"
    try:
        r = subprocess.run([sys.executable, _join(root, "scripts", "progress.py"), SPEC], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
        out = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return f"rspec: not run: progress.py failed ({e})"
    if not isinstance(out, dict):
        return "rspec: not run: progress.py printed no JSON object"
    pending = ", ".join(str(p) for p in out.get("pending") or []) or "none"
    return f"rspec: stage {out.get('stage') or 'none'}, next {out.get('next') or 'none'}, pending {pending}"


def phase_before_gate5():
    """What to call the phase when contracts are locked and prod-ready is not."""
    slices = slice_states()
    if not slices:
        # A slice plan that exists but reads as no slices is a parse failure, not a finished build.
        plan = f"{SPEC}/build-plan.md"
        return f"G5 build ({plan} has no `## Slice` this script can read)" if os.path.exists(plan) else None
    done = [s for s in slices if s["status"] in ("done", "deployed")]
    nxt = next((s for s in slices if s["status"] not in ("done", "deployed")), None)
    count = f"{len(done)}/{len(slices)} slices"
    if nxt:
        return f"G5 build — next unfinished slice {nxt['id']} ({nxt['status']}), {count} done"
    return f"GP production readiness ({count} done)"


# Free-text fields (title, reason, locked_by) go through here before being written —
# unquoted plain scalars break as soon as the value contains a colon-space, a leading
# indicator char, a trailing colon, or a "#" (comment start). Quoting is conditional
# (not "always double-quote") so pre-existing simple values round-trip unchanged.
def needs_quoting(s):
    return re.search(r": |:\Z|^[-?:,\[\]{}#&*!|>'\"%@`]|\n", s) is not None


def yaml_str(s):
    if s is None:
        return "undefined"
    if needs_quoting(s):
        return '"' + s.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"') + '"'
    return s


def unquote(s):
    if s is not None and re.match(r'".*"\Z', s):
        return s[1:-1].replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
    return s


def parse_lock(gid):
    text = read_text(_join(LOCKS, f"{gid}.yaml"))

    def get(k):
        m = re.search(rf"^{k}: (.*)$", text, re.M)
        return unquote(m.group(1).strip()) if m else None

    bm = re.search(r"^protects:[ \t]*\n((?:[ \t]+.*\n?)*)", text, re.M)
    block = (bm.group(1) if bm else "") or ""
    protects = [m.group(1).strip() for m in re.finditer(r"^  - (.+)$", block, re.M)]
    return {"id": gid, "title": get("title"), "status": get("status"), "locked_at": get("locked_at"),
            "text": text, "protects": protects}


def files_under(p):
    """Paths come back with `/` on every platform. They become artifact_hashes keys, which
    validate.py re-reads; a lock cut on Windows with join()'s backslashes would name files
    that do not exist on any other machine the workbench is cloned to.

    Directory order is breadth-first with each directory's names sorted bytewise, which is what
    the Node twin's recursive readdir produced, so a lock written by either lists files in the
    same order on every platform."""
    if not os.path.exists(p):
        return []
    if os.path.isfile(p):
        return [p]
    found, queue = [], [p]
    for d in queue:
        for n in sorted(os.listdir(d)):
            f = _join(d, n)
            found.append(f)
            if os.path.isdir(f):
                queue.append(f)
    return [f.replace(os.sep, "/") for f in found if os.path.isfile(f)]


def sha(f):
    with open(f, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _js_integer(s):
    """`Number.isInteger(Number(s))` for the tag suffix: `v1.0` and an empty suffix both count."""
    if re.fullmatch(r"\s*[+-]?[0-9]+(\.[0-9]*)?([eE][+-]?[0-9]+)?\s*", s) is None:
        return False, 0
    n = float(s)
    return n.is_integer(), int(n) if n.is_integer() else 0


def _iso_now():
    t = datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


# rspec's stages in order (its rspec_lib.STAGES); copied, not imported, because a vendored
# script must run without rspec installed. If rspec adds a stage, add it here too.
RSPEC_STAGES = ["init", "discovered", "features-approved", "stories", "tech", "handoff"]


def rspec_config():
    """docs/rspec.json, or {} when it is missing or unreadable (the checks then refuse)."""
    try:
        cfg = json.loads(read_text(_join(SPEC, "rspec.json")))
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _lock_gate1_checks(gid):
    # Gate 1 is the user's approval of the feature list, and rspec records that approval as its
    # stage `features-approved`. Locking before it would hash a list rspec itself still treats as
    # a draft, with the departures written only after approval (rspec features step 6).
    stage = rspec_config().get("stage")
    if stage not in RSPEC_STAGES or RSPEC_STAGES.index(stage) < RSPEC_STAGES.index("features-approved"):
        print(f"Cannot lock {gid}: {SPEC}/rspec.json says stage {stage or 'none'}; Gate 1 locks the feature list "
              f"after rspec records its approval (stage features-approved). Finish /rspec:features first.",
              file=sys.stderr)
        return 1
    # 05 P8: a rebuild is built for production, so rspec's goal is `production` (which makes rspec require a
    # Verification per NFR and the readiness checklist GP walks). The skill sets it at rspec:init.
    if rspec_config().get("goal") != "production":
        print(f"Cannot lock {gid}: {SPEC}/rspec.json goal is {rspec_config().get('goal') or 'empty'}; a rebuild's goal is "
              f"production (05 P8). Set it with the user and re-run the stages it changes.", file=sys.stderr)
        return 1
    return None


def proposed_adrs():
    """ADR files under docs/decisions/ whose own Status line still says Proposed. rspec's ADR template
    writes `- Status: Proposed`, and its handoff step 1 rewrites it to Accepted or Rejected."""
    folder = _join(SPEC, "decisions")
    out = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".md"):
            # `- Status: Proposed`, `status: proposed` or `**Status:** Proposed`: the word after it.
            m = re.search(r"^\W*status\W+(\w+)", read_text(_join(folder, name)), re.M | re.I)
            if m and m.group(1).lower() == "proposed":
                out.append(name)
    return out


def _lock_gate3_checks(gid):
    # An ADR the user decided says so. Nothing else moves Proposed to Accepted, and the Kutt
    # rebuild locked eleven ADRs whose own files said proposed until the orchestrator noticed and
    # changed them by hand: the hash would have pinned "proposed" as the locked decision. rspec owns
    # the ADRs; the playbook's concern list is no longer checked against them.
    undecided = proposed_adrs()
    if undecided:
        print(f"Cannot lock {gid}: still Status: Proposed in {SPEC}/decisions/: {', '.join(undecided)}. "
              f"Decide each with the user (rspec handoff step 1) first.", file=sys.stderr)
        return 1
    # The stack a code repo is created from is locked with the ADRs that chose it: scaffold-repo reads
    # adr/'s scaffold manifest at G5, so a gate-3 without one is a stack nothing can create.
    import playbook
    res = playbook.check_playbook()
    scaffold = res.get("scaffold") or {}
    problems = res["problems"] + (scaffold.get("problems") or [] if res["disabled"] else [])
    if res["missing_vendored"]:
        problems.append(f"{playbook.VENDORED_PLAYBOOK} is not vendored")
    if problems:
        print(f"Cannot lock {gid}: no scaffold manifest a code repo can be created from:\n  " + "\n  ".join(problems)
              + f"\n  {playbook.PLAYBOOK_REMEDY}", file=sys.stderr)
        return 1
    return None


def _lock_gate2_checks(gid):
    # Gate 2 locks the slices rspec's handoff cut, and handoff requires a finished audit and a
    # settled verify: a slice plan cut before them sizes slices on criteria that may still change
    # level or wording. Verify is skipped only when the spec says the reference does not run.
    missing = []
    if not os.path.exists(_join(SPEC, "audit", "summary.md")):
        missing.append(f"{SPEC}/audit/summary.md (run /rspec:audit)")
    kind = ((rspec_config().get("reference") or {}).get("run") or {}).get("kind")
    if kind != "none" and not os.path.exists(_join(SPEC, "verify", "summary.md")):
        missing.append(f"{SPEC}/verify/summary.md (run /rspec:verify)")
    if missing:
        print(f"Cannot lock {gid}: rspec's audit and verify have not finished: missing {'; '.join(missing)}.",
              file=sys.stderr)
        return 1
    # The lock wants a clean tree, so locking before the split would force the whole bundle, hidden share
    # included, into the history every lane holds as a submodule (05 P4).
    if os.path.exists(_join(SPEC, "acceptance", "manifest.json")) and not os.path.exists(_join("plan", "holdout.json")):
        print(f"Cannot lock {gid}: no holdout split yet. Run python3 scripts/holdout.py split, then commit the "
              f"workbench (the open bundle's first commit), then lock {gid}.", file=sys.stderr)
        return 1
    return None


def posture():
    """sources.yaml reference.posture, resolved as validate.py and the reference guard resolve it
    (empty: own-code for kind own-code, else observe; an unknown value counts as strict).
    Line-parsed, like them; change the three together."""
    try:
        text = read_text("sources.yaml") + "\n"
    except OSError:
        text = ""
    block = re.search(r"^reference:[ \t]*\n((?:(?:[ \t]+.*)?\n)*)", text, re.M)

    def field(key):
        f = block and re.search(rf"^[ \t]+{key}:[ \t]*(.*)$", block.group(1), re.M)
        return re.split(r"\s+#", f.group(1))[0].strip().strip("\"'") if f else ""

    p = field("posture")
    if not p:
        return "own-code" if field("kind") == "own-code" else "observe"
    return p if p in ("strict", "observe", "own-code") else "strict"


LEVEL2_FLOOR = 0.9  # 05 P2: MVP criteria at level 2 before Gate 4 locks, for observe/own-code


def _lock_gate4_checks(gid, argv):
    # Level 2 means a test recorded against the running reference (contracts C3); below it a
    # criterion's test was written from the spec, so the builder's tests agree with the spec and
    # nothing says the spec agrees with the product. Under `strict` the spec side may not run
    # what it would take to record more, so the share is shown, never refused. Returns
    # (exit code or None, extra lock lines).
    # The hidden tests are drawn before this lock, and the lock pins the draw (05 P4): the manifest it
    # hashes must be the one the split left, or the recorded list describes a different bundle. A re-verify
    # after an amend rebuilds the manifest without the hidden entries; reconcile restores them and re-pins
    # the record, and the lock then wants both committed (it refuses a dirty tree).
    try:
        import holdout
        changed, err = holdout.reconcile()
    except ImportError:
        changed, err = False, "scripts/holdout.py is missing from the workbench"
    if err:
        print(f"Cannot lock {gid}: {err}", file=sys.stderr)
        return 1, ""
    if changed:
        print(f"Cannot lock {gid} yet: holdout.py reconcile restored the hidden entries a re-verify dropped. Commit "
              f"{SPEC}/acceptance/manifest.json and plan/holdout.json, then lock {gid} again.", file=sys.stderr)
        return 1, ""
    try:
        split = json.loads(read_text(_join("plan", "holdout.json")))
    except (OSError, ValueError):
        split = None
    manifest = _join(SPEC, "acceptance", "manifest.json")
    if not isinstance(split, dict):
        print(f"Cannot lock {gid}: no holdout split yet (plan/holdout.json). Run python3 scripts/holdout.py split "
              f"first; it draws the hidden tests this lock records.", file=sys.stderr)
        return 1, ""
    if not os.path.exists(manifest) or split.get("manifest_sha256") != sha(manifest):
        print(f"Cannot lock {gid}: {manifest} changed after the holdout split (plan/holdout.json records another "
              f"version). The draw would no longer match the bundle; ask the user before re-drawing.", file=sys.stderr)
        return 1, ""
    holdout = (f"holdout:\n  seed: {split.get('seed')}\n  count: {split.get('count')}\n"
               f"  list_sha256: {split.get('list_sha256')}\n")
    try:
        lock = json.loads(read_text(_join(SPEC, "criteria.lock.json")))
        rows = [c for c in lock.get("criteria") or [] if isinstance(c, dict) and c.get("priority") == "MVP"]
    except (OSError, ValueError, AttributeError):
        print(f"Cannot lock {gid}: {SPEC}/criteria.lock.json is missing or not valid JSON. Run /rspec:check to "
              f"write it.", file=sys.stderr)
        return 1, ""
    if not rows:
        print(f"Cannot lock {gid}: {SPEC}/criteria.lock.json lists no MVP criterion.", file=sys.stderr)
        return 1, ""
    share = sum(1 for c in rows if c.get("level") == 2) / len(rows)
    figure = f"MVP level 2: {round(share * 100)}% ({sum(1 for c in rows if c.get('level') == 2)} of {len(rows)})"
    if share >= LEVEL2_FLOOR:
        print(figure)
        return None, holdout
    pos = posture()
    if pos == "strict":
        print(f"{figure}, below {round(LEVEL2_FLOOR * 100)}%; posture strict, so reported, not refused.")
        return None, holdout
    reason = argv[argv.index("--accept-level2") + 1] if "--accept-level2" in argv[:-1] else None
    by = argv[argv.index("--by") + 1] if "--by" in argv[:-1] else None
    if not reason or not by:
        print(f"Cannot lock {gid}: {figure}, below {round(LEVEL2_FLOOR * 100)}% with posture {pos}. Record more "
              f"tests with /rspec:verify, or lock with the user's signed reason:\n"
              f'  python3 scripts/gate.py lock {gid} --accept-level2 "<reason>" --by "<name>"', file=sys.stderr)
        return 1, ""
    print(f"{figure}, below {round(LEVEL2_FLOOR * 100)}%; locking on {by}'s signed reason.")
    return None, holdout + (f"level2_waiver:\n  share: {round(share, 4)}\n  floor: {LEVEL2_FLOOR}\n  posture: {pos}\n"
                  f"  reason: {yaml_str(reason)}\n  by: {yaml_str(by)}\n  at: {_iso_now()}\n")


def _lock_gate5_checks(gid):
    # -------------------------------------------------------------------------
    # Gate 5 refuses to lock while the newest equivalence run has a failure nobody explained.
    #
    # Gate 5 is terminal. Nothing downstream catches an overclaim here, and a red equivalence trace is the least deniable thing in
    # the project: it says the rebuild returns something the old system did not, on traffic
    # recorded from the old system before the rebuild existed. Locking over it would be the
    # pipeline's own definition of done disagreeing with its own evidence.
    #
    # It refuses on UNDECIDED failures only. An intended difference — the Gate 4 contract renamed
    # a field, a bug was deliberately not reproduced — is legitimate and expected; it just has to
    # be on the record. `python3 scripts/equiv.py accept "<trace>" --reason "..."` writes that
    # record, and this check reads it. So the gate is not "every trace green", it is "every red
    # trace explained", which is the same standard the readiness checklist applies to everything
    # else.
    #
    # Standard library only by the same rule as the rest of this file: the JUnit is regex-read for
    # failing testcase names (acsuite.py makes the same argument about JUnit's fixed shape), and
    # the decision log is markdown with one machine-readable token per accepted trace.
    #
    # From 3.0.0 (05 P8) it also refuses on everything else P8 lists, all reported at once so one
    # attempt shows the whole gap: rspec's readiness checklist, GP's NFR evidence, the hidden suites, open
    # high findings, proposed departures and MVP criteria below level 1. The equivalence check stays last.
    # -------------------------------------------------------------------------
    problems = _gate5_problems()
    if problems:
        print(f"Cannot lock {gid}:\n" + "\n".join(f"  - {p}" for p in problems), file=sys.stderr)
    parity_dir = "parity"
    runs = []
    if os.path.exists(parity_dir):
        for f in os.listdir(parity_dir):
            m = re.fullmatch(r"([0-9]{4}-[0-9]{2}-[0-9]{2})-equiv\.xml", f)
            if m:
                runs.append({"date": m.group(1), "path": _join(parity_dir, m.group(0))})
        runs.sort(key=lambda r: r["date"], reverse=True)
    if runs:
        with open(runs[0]["path"], encoding="utf-8", errors="replace", newline="") as fh:
            xml = fh.read()
        # One chunk per <testcase>, so a <failure> is attributed to the case that contained it.
        failing = []
        for chunk in re.split(r"<testcase\b", xml, flags=re.A)[1:]:
            end = chunk.find("</testcase>")
            body = chunk if end == -1 else chunk[:end]
            nm = re.search(r'\bname="([^"]*)"', body, re.A)
            name = (nm.group(1) if nm else "") or "(unnamed)"
            if re.search(r"<(failure|error)\b", body, re.A):
                failing.append(name)
        if failing:
            # 3.0.0 (05 P7): an accepted difference is a decided departure in docs/departures.yaml (rule
            # `equiv-trace:<name>`, written by `equiv.py accept`), not a line in parity/equiv/DECISIONS.md.
            try:
                import departures
                undecided = [n for n in failing if not departures.for_trace(n)]
            except Exception as e:  # missing or unreadable registry: nothing is explained, and the lock says why
                print(f"docs/departures.yaml could not be read ({e}); no red trace counts as explained.", file=sys.stderr)
                undecided = list(failing)
            if undecided:
                print(f"Cannot lock {gid}: the newest equivalence run ({runs[0]['path']}) has "
                      f"{len(undecided)} failing trace(s) that no departure explains:\n" +
                      "\n".join(f"  - {n}" for n in undecided) +
                      f"\n\n  A red trace means the rebuild returns something the legacy system did not, on "
                      f"traffic recorded from the legacy system before the rebuild existed. Gate 5 is "
                      f"terminal — nothing after it catches this."
                      f"\n  Fix the difference and re-run `python3 scripts/equiv.py replay --all`, or, if the "
                      f"difference is intended, put it on the record:"
                      f'\n    python3 scripts/equiv.py accept "<trace name>" --reason "..." --by "<who decided>"'
                      f"\n  Accepting does not make the trace green. It makes it explained, which is all this "
                      f"gate asks of anything else that is still imperfect.", file=sys.stderr)
                return 1
            print(f"Equivalence: {len(failing)} red trace(s) in {runs[0]['path']}, each explained by a departure.")
    return 1 if problems else None


def _gate5_problems():
    """P8's refusals other than equivalence, each a line naming what to fix."""
    out = []
    ready = _join(SPEC, "production-readiness.md")
    if not os.path.exists(ready):
        out.append(f"{ready} is missing (rspec:handoff writes it when goal is production)")
    else:
        category = None
        for line in read_text(ready).split("\n"):
            h = re.match(r"^##\s+(.+?)\s*$", line)
            if h:
                category = h.group(1)
            m = re.match(r"^\s*-\s*\[ \]\s+(\S.*)$", line)
            if m:
                out.append(f"readiness, {category or 'unsectioned'}: not done: {m.group(1)}")
    try:
        import gp
        out += [f"NFR evidence: {p}" for p in gp.problems()]
    except ImportError:
        out.append("scripts/gp.py is missing: the NFR evidence cannot be checked")
    try:
        import holdout
        rec = json.loads(read_text(holdout.RECORD)) if os.path.exists(holdout.RECORD) else {}
        for sid, ids in sorted((rec.get("slices") or {}).items()):
            if not ids:
                continue
            p = _join("parity", "holdout", f"{sid}.json")
            if not os.path.exists(p):
                out.append(f"hidden suite {sid}: not run (python3 scripts/holdout.py run {sid})")
                continue
            for x in json.loads(read_text(p)).get("results") or []:
                if x.get("result") not in ("pass", "explained"):
                    out.append(f"hidden suite {sid}: {x.get('criterion')} {x.get('result')} with no departure")
        slices = sorted(holdout.slices())
        out += [f"the holdout repo is reachable from a code repo: {b}" for b in holdout.exposure(holdout.holdout_dir())]
    except (ImportError, OSError, ValueError) as e:
        out.append(f"hidden suites not checked ({e})")
        slices = []
    try:
        import boundary
        for sid in slices:
            try:
                out += [f"open high finding {f['id']} ({f['class']}, slice {sid}): route.py {sid}"
                        for f in boundary._open_findings(sid) if f.get("severity") == "high"]
            except boundary.NotRun as e:
                out.append(f"open findings of {sid} not counted: not run: {e}")
    except ImportError:
        out.append("scripts/boundary.py is missing: open findings cannot be checked")
    try:
        import departures
        out += [f"departure {d.get('id')} is still proposed: the user decides it" for d in departures.proposed()]
    except Exception as e:
        out.append(f"docs/departures.yaml could not be read ({e})")
    try:
        lock = json.loads(read_text(_join(SPEC, "criteria.lock.json")))
        out += [f"MVP criterion {c['id']} is below level 1" for c in lock.get("criteria") or []
                if isinstance(c, dict) and c.get("priority") == "MVP" and c.get("level") == 0]
    except (OSError, ValueError):
        out.append(f"{SPEC}/criteria.lock.json is missing or not JSON")
    return out


def _git(args, capture_stdout=True):
    # stderr is left inherited, as the Node twin's execSync did: a "not a git repository"
    # note is the only hint why the commit and tag were skipped.
    return subprocess.run(["git", *args], check=True,
                          stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
                          stderr=None if capture_stdout else subprocess.DEVNULL,
                          text=True, encoding="utf-8")


def cmd_lock(gid, lock, argv):
    prev_open = [l for l in (parse_lock(g) for g in ORDER[:ORDER.index(gid)]) if l["status"] != "locked"]
    if prev_open:
        print(f"Cannot lock {gid}: earlier gate(s) still open: {', '.join(l['id'] for l in prev_open)}", file=sys.stderr)
        return 1
    extra = ""
    for check, which in ((_lock_gate1_checks, "gate-1"), (_lock_gate3_checks, "gate-3"), (_lock_gate2_checks, "gate-2"),
                         (_lock_gate5_checks, "gate-5")):
        if gid == which:
            rc = check(gid)
            if rc is not None:
                return rc
    if gid == "gate-4":
        rc, extra = _lock_gate4_checks(gid, argv)
        if rc is not None:
            return rc

    # artifact_hashes below is computed from the WORKING TREE, but the lock commit further
    # down stages only the lock file itself. If any protected (or other) file is dirty, the
    # hash recorded here describes content that never lands in the gate-tagged commit — a
    # code repo pinning that tag then gets the OLD file while the lock claims the NEW hash.
    # Refuse rather than let that drift through silently. (Not `git add -A`: sweeping in
    # unrelated in-progress work would land it in a "gate-N: locked" commit uninvited.)
    # Forward slashes, not join(): git prints `/` on every platform, and on Windows join() gives
    # `locks\gate-N.yaml`, which never equals it — the lock file was reported as dirty against
    # itself and every lock refused.
    lock_path = f"{LOCKS}/{gid}.yaml"
    try:
        out = _git(["status", "--porcelain"]).stdout
        dirty = [f for f in (l[3:].strip() for l in out.split("\n") if l) if f != lock_path]
        if dirty:
            print(f"Cannot lock {gid}: working tree has uncommitted changes outside {lock_path}:\n" +
                  "\n".join(f"  {f}" for f in dirty) +
                  f"\nCommit or stash these first, then lock — otherwise the hashes recorded would not match "
                  f"what the gate tag actually points at.", file=sys.stderr)
            return 1
    except Exception:
        pass  # git unavailable — same fallback as the commit/tag step below

    # Union in anything this gate must protect that its scaffolded `protects:` predates.
    # Absent directories contribute no files and no hashes: the line appears in the lock file and
    # protects an empty set, which is the correct description of that project.
    protects = list(dict.fromkeys([*lock["protects"], *REQUIRED_PROTECTS.get(gid, [])]))
    added = [p for p in protects if p not in lock["protects"]]
    if added:
        print(f"Adding to {gid} protects: {', '.join(added)} "
              f"(required by this plugin version; this workbench was scaffolded before it).")

    hashes = [f"  {f}: {sha(f)}" for p in protects for f in files_under(p)]
    if not hashes:
        print(f"Nothing to lock: no files under {', '.join(protects)}", file=sys.stderr)
        return 1
    flag = argv.index("--by") if "--by" in argv else -1
    by = (argv[flag + 1] if 0 <= flag < len(argv) - 1 else None) or os.environ.get("USER") or "unknown"
    now = _iso_now()
    if "history: []" in lock["text"]:
        history = f"history:\n  - action: locked\n    at: {now}\n    reason: {yaml_str('gate review approved')}"
    else:
        history = (re.search(r"history:[\s\S]*\Z", lock["text"]).group(0).rstrip() +
                   f"\n  - action: locked\n    at: {now}\n    reason: {yaml_str('gate review approved')}")
    protects_lines = "\n".join(f"  - {p}" for p in protects)
    hash_lines = "\n".join(hashes)
    with open(_join(LOCKS, f"{gid}.yaml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(
            f"gate: {gid}\n"
            f"title: {yaml_str(lock['title'])}\n"
            f"status: locked\n"
            f"locked_at: {now}\n"
            f"locked_by: {yaml_str(by)}\n"
            f"protects:\n"
            f"{protects_lines}\n"
            f"artifact_hashes:\n"
            f"{hash_lines}\n"
            f"{extra}"
            f"{history}\n")
    try:
        # Gate tags are IMMUTABLE and versioned: each lock mints the next vN and never moves
        # an existing one.
        #
        # This used to be `git tag -f ${id}/v1`, and force-moving it was a real hazard rather
        # than a tidiness question. Code repos consume this workbench as a submodule pinned by
        # COMMIT, and resolve that pin's name with `git describe --exact-match`. A submodule
        # clone that had already fetched `gate-4/v1` kept resolving it to the OLD commit after
        # a reopen, so the consumer's contract-sync reported success while pinning the previous
        # contract — the exact drift that ceremony exists to make impossible. Found during S9
        # stage 4 (plan/backlog.md); nothing was mis-synced only because neither reopen that
        # day touched openapi.yaml.
        #
        # A moving `latest` alias was rejected for the same reason: any mutable ref reintroduces
        # "the name resolves differently depending on when you last fetched".
        existing = [t.strip() for t in _git(["tag", "-l", f"{gid}/v*"]).stdout.split("\n") if t.strip()]
        nxt = 1
        for t in existing:
            is_int, n = _js_integer(t[len(f"{gid}/v"):])
            if is_int and n > nxt - 1:
                nxt = n + 1
        tag = f"{gid}/v{nxt}"
        _git(["add", f"{LOCKS}/{gid}.yaml"], capture_stdout=False)
        _git(["commit", "-qm", f"{gid}: locked"], capture_stdout=False)
        _git(["tag", tag], capture_stdout=False)
        print(f"{gid} locked, committed, tagged {tag}.")
        # The commit and the tag are both local until pushed, and nothing in this pipeline pushes
        # on anyone's behalf. Two traps make it worth spelling out here, at the moment of locking,
        # rather than trusting a doc step:
        #   - `git push` alone sends no tags at all, so the commit lands and the pin does not. A
        #     code repo then gets `pathspec '${tag}' did not match` from its submodule checkout —
        #     or, worse, silently stays on the previous vN and keeps building against the old
        #     contract, which is exactly the drift the immutable-tag scheme exists to prevent.
        #   - `--follow-tags` looks like the fix and is not: it pushes annotated tags only, and
        #     these are lightweight (`git tag ${tag}`). Naming a command that quietly does nothing
        #     would be worse than naming none.
        print("      Push both now — the tag is a submodule pin, not a label:")
        print("        git push && git push --tags")
        if nxt > 1:
            print(f"NOTE: {tag} is a NEW tag — {gid}/v{nxt - 1} still points at the previous lock.")
            print("      Every code repo pinning this gate must re-pin deliberately (after the push above):")
            print(f"        git -C <submodule> fetch --tags && git -C <submodule> checkout --detach {tag}")
            print("      A repo that does not re-pin keeps building against the older contract,")
            print("      which is now visible rather than silent.")
    except Exception:
        print(f"{gid} locked. Commit and tag manually (git unavailable or dirty tree).")
    return 0


def cmd_reopen(gid, lock, argv):
    flag = argv.index("--reason") if "--reason" in argv else -1
    reason = argv[flag + 1] if 0 <= flag < len(argv) - 1 else None
    if not reason:
        print('Reopening requires --reason "..." — it is a formal, logged event.', file=sys.stderr)
        return 1
    body = lock["text"]
    body = re.sub(r"^status: locked$", "status: open", body, count=1, flags=re.M)
    body = re.sub(r"^locked_at: .*$\n", "", body, count=1, flags=re.M)
    body = re.sub(r"^locked_by: .*$\n", "", body, count=1, flags=re.M)
    body = re.sub(r"^artifact_hashes:[\s\S]*?(?=history:)", "", body, count=1, flags=re.M)
    body = body.rstrip() + f"\n  - action: reopened\n    at: {_iso_now()}\n    reason: {yaml_str(reason)}\n"
    with open(_join(LOCKS, f"{gid}.yaml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    print(f"{gid} reopened: {reason}\nRemember: downstream artifacts built on this gate may now be stale.")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if not os.path.exists(_join(LOCKS, "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    cmd = argv[0] if argv else None

    if cmd == "status" or not cmd:
        locks = [parse_lock(g) for g in ORDER]
        for l in locks:
            mark = "LOCKED" if l["status"] == "locked" else "open  "
            at = f"  ({l['locked_at']})" if l["locked_at"] else ""
            print(f"{l['id']}  [{mark}]  {_undef(l['title'])}{at}")
        print(rspec_progress_line())
        current = next((l for l in locks if l["status"] != "locked"), None)
        if not current:
            print("\nAll gates locked — pipeline complete.")
            return 0
        phase = (current["id"] == "gate-5" and phase_before_gate5()) or PHASE_BEFORE[current["id"]]
        print(f"\nCurrent phase: {phase} (working toward {current['id']})")
        return 0

    gid = argv[1] if len(argv) > 1 else None
    if gid not in ORDER:
        print(f"Unknown gate: {_undef(gid)}", file=sys.stderr)
        return 1
    lock = parse_lock(gid)
    if cmd == "lock":
        return cmd_lock(gid, lock, argv)
    if cmd == "reopen":
        return cmd_reopen(gid, lock, argv)
    print('Usage: gate.py status | lock <gate-id> [--by <name>] [--accept-level2 "<reason>"] | reopen <gate-id> --reason "..."', file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
