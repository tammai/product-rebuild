#!/usr/bin/env python3
"""gate.py — view and manage gate locks. Run from the workbench root.
Usage:
  python3 scripts/gate.py status
  python3 scripts/gate.py lock <gate-id> [--by <name>]
  python3 scripts/gate.py reopen <gate-id> --reason "..."
Locking records sha256 hashes of every file under the gate's `protects:` paths.

Standard library only, plus guarded imports of its siblings (erd.py, playbook.py): lock files use a
fixed YAML subset written and parsed here, so `status` keeps answering on a workbench whose other
scripts are missing or broken. It is a script and not a line in a doc because the lock is the
pipeline's one irreversible act and the hashes must be computed the same way every time.
"""
from __future__ import annotations

import hashlib
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
# missing (see the erd import in `lock` below).
def read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        return re.sub(r"\r\n?", "\n", fh.read())


def _join(*parts):
    return os.path.normpath(os.path.join(*parts))


def _undef(v):
    """A missing lock field printed as the word `undefined` in the Node twin; kept so output matches."""
    return "undefined" if v is None else v


ORDER = ["gate-1", "gate-2", "gate-3", "gate-4", "gate-5"]

# Paths a gate protects REGARDLESS of what its lock file's `protects:` list says.
#
# `protects:` is written once by rebuild_init.py at scaffold time, which means a path
# added to a gate by a later release reaches new workbenches only. That is fine for a
# script (the plugin's copy still runs) and not fine for a lock: a gate-1 that does not
# hash findings/rules/ leaves the Rule Cards editable after the taxonomy locks, in every
# workbench scaffolded before 0.17.0 — silently, and exactly in the projects most likely
# to have rules worth locking.
#
# So the list is unioned in here at lock time and written into the lock file, which also
# hands it to gate-guard for free: that hook reads `protects:` out of the locked file,
# so a path this adds is enforced by the guard from the moment the gate locks.
#
# Rules are TAXONOMY, not design — the same argument that puts matrix/features.yaml behind
# gate-1. A rule discovered later enters the way a late feature does: added under the
# existing structure, never restructuring it.
REQUIRED_PROTECTS = {
    "gate-1": ["findings/rules/"],
}
PHASE_BEFORE = {
    "gate-1": "G2 feature matrix", "gate-2": "G3 milestone slicing",
    "gate-3": "G4a system design", "gate-4": "G4b data model + contracts",
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

    Standard library only by the same rule as the lock files: a fixed YAML subset, parsed here.
    plan/progress.yaml's `slices:` map wins over plan/slices.yaml's own `status:`, matching
    parity.py's overlay precedence."""
    def read(p):
        return read_text(p) if os.path.exists(p) else ""

    overlay = {}
    progress = read("plan/progress.yaml")
    # Indented lines OR blank ones: a hand-written progress file groups its entries with blank
    # lines and comments, and a pattern that stops at the first blank line silently reads only the
    # first group — which is a wrong phase rather than an error. The block still ends at the next
    # top-level key, because that line is neither indented nor empty.
    slices_block = re.search(r"^slices:\n((?:(?:[ \t]+.*)?\n)*)", progress, re.M)
    if slices_block:
        for m in re.finditer(r"^\s+(S[0-9]+):\s*([a-z-]+)", slices_block.group(1), re.M):
            overlay[m.group(1)] = m.group(2)
    plan = read("plan/slices.yaml")
    out = []
    # One entry per `- id: SN`, carrying the nearest following `status:` before the next entry.
    entries = re.split(r"^- id: ", plan, flags=re.M)[1:]
    for e in entries:
        idm = re.match(r"(S[0-9]+)", e)
        if not idm:
            continue
        sid = idm.group(1)
        own = re.search(r"^\s{2}status:\s*([a-z-]+)", e, re.M)
        out.append({"id": sid, "status": overlay.get(sid) or (own.group(1) if own else None) or "pending"})
    return out


def phase_before_gate5():
    """What to call the phase when contracts are locked and prod-ready is not."""
    slices = slice_states()
    if not slices:
        return None  # no slice plan — fall back to the table above
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


def _lock_gate4_checks(gid):
    # Gate 4 locks the data model as well as the three contract layers, and G4b drafts it
    # FIRST — Gate 3 decided where data lives, this decides what it is. The check has to be
    # here rather than in validate.py: gate status is open|locked with nothing in between,
    # so a validator that fires on `locked` reports a missing data model only after the tag
    # is cut, turning a one-line edit into a reopen and a new gate-4/vN.
    #
    # Imported here, not at the top of the file: `erd.py` is a newer script than the four
    # rebuild_init has always copied, so a workbench upgraded by hand can be missing it. A
    # top-level import makes that absence take out `gate.py status` too — the command the
    # orchestration protocol runs first, and the one thing that must never stop answering.
    # Lock is the only path that needs it, so lock is the only path that fails on it.
    try:
        import erd
    except ImportError:
        print(f"Cannot lock {gid}: scripts/erd.py is missing, so the data model cannot be "
              f"checked. Copy it from the plugin's skills/rebuild-pipeline/scripts/ alongside the copies "
              f"of validate.py and gate.py already in this workbench.", file=sys.stderr)
        return 1
    dm = erd.check_data_model()
    issues = list(dm["problems"])
    if dm["missing"]:
        issues.append(f"{erd.DATA_MODEL_DIR}/ contains no .mermaid file")
    if issues:
        body = "\n".join(f"  {i}" for i in issues) + f"\n  {erd.DATA_MODEL_REMEDY}"
        if erd.is_legacy_workbench():
            print(f"WARNING: locking {gid} without a checked data model:\n{body}\n"
                  f"  Allowed because this workbench predates schema_version 0.2.0. To enforce it, add the\n"
                  f"  data model and set schema_version: \"0.2.0\" in locks/pipeline.yaml.", file=sys.stderr)
        else:
            print(f"Cannot lock {gid}:\n{body}", file=sys.stderr)
            return 1
    return None


def _lock_gate3_checks(gid):
    # Gate 3 locks the ADRs AND the playbook they cite. G4a vendors the selected playbook to
    # adr/playbook.md precisely so the citations survive a plugin upgrade — a copy that never
    # arrived leaves every "cites §7" pointing at whatever the registry says months from now.
    # The undecided-concerns check is the other half: "every cross-cutting concern decided"
    # was a prose exit criterion until the playbook's concerns: map made it a list, and a list
    # is checkable. Same placement reasoning as gate-4's data model — a validator that fires
    # on `locked` reports the gap only after the tag is cut.
    try:
        import playbook as pb
    except ImportError:
        print(f"Cannot lock {gid}: scripts/playbook.py is missing, so the architecture "
              f"playbook cannot be checked. Copy it from the plugin's skills/rebuild-pipeline/scripts/ "
              f"alongside the copies of validate.py and gate.py already in this workbench.", file=sys.stderr)
        return 1
    res = pb.check_playbook()
    # No playbook means no registry manifest, so the project's own adr/scaffold.json stands in.
    # It is held to the same checks, because G5 scaffolds from it exactly as it would from a
    # playbook's, and "blank-slate ADRs" was never meant to include "no way to create the repo".
    if res["disabled"] and res["scaffold"] and res["scaffold"]["problems"]:
        body = "\n".join(f"  {i}" for i in res["scaffold"]["problems"])
        if pb.is_pre_playbook_workbench():
            print(f"WARNING: locking {gid} without a scaffold manifest:\n{body}", file=sys.stderr)
        else:
            print(f"Cannot lock {gid}:\n{body}", file=sys.stderr)
            return 1
    if not res["disabled"]:
        issues = list(res["problems"])
        if res["missing_vendored"]:
            by = ("by default: sources.yaml's architecture.playbook is empty"
                  if res["selected_by"] == "default" else "in sources.yaml")
            issues.append(f'{pb.VENDORED_PLAYBOOK} does not exist — G4a step 0.3 must vendor the '
                          f'"{res["selected"]}" playbook (selected {by}) before this gate can lock, so the '
                          f'ADR citations are pinned by the lock')
        if res["undecided"]:
            issues.append(f"no ADR for concern(s): {', '.join(res['undecided'])} "
                          f"(every key in the playbook's concerns: map needs one, even to record N/A)")
        if issues:
            body = "\n".join(f"  {i}" for i in issues) + f"\n  {pb.PLAYBOOK_REMEDY}"
            if pb.is_pre_playbook_workbench():
                print(f"WARNING: locking {gid} without a checked architecture playbook:\n{body}\n"
                      f"  Allowed because this workbench predates schema_version 0.3.0. To enforce it, backfill\n"
                      f"  and set schema_version: \"0.3.0\" in locks/pipeline.yaml.", file=sys.stderr)
            else:
                print(f"Cannot lock {gid}:\n{body}", file=sys.stderr)
                return 1
    return None


def _lock_gate5_checks(gid):
    # -------------------------------------------------------------------------
    # Gate 5 refuses to lock while the newest equivalence run has a failure nobody explained.
    #
    # Gate 5 is terminal. Nothing downstream catches an overclaim here, which is why its rubric is
    # almost entirely about honesty — and a red equivalence trace is the least deniable thing in
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
    # -------------------------------------------------------------------------
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
            log = _join("parity", "equiv", "DECISIONS.md")
            decisions = read_text(log) if os.path.exists(log) else ""
            accepted = {m.group(1) for m in re.finditer(r"^\s*-\s*accepted:\s*`([^`]+)`", decisions, re.M)}
            undecided = [n for n in failing if n not in accepted]
            if undecided:
                print(f"Cannot lock {gid}: the newest equivalence run ({runs[0]['path']}) has "
                      f"{len(undecided)} failing trace(s) that no decision explains:\n" +
                      "\n".join(f"  - {n}" for n in undecided) +
                      f"\n\n  A red trace means the rebuild returns something the legacy system did not, on "
                      f"traffic recorded from the legacy system before the rebuild existed. Gate 5 is "
                      f"terminal — nothing after it catches this."
                      f"\n  Fix the difference and re-run `python3 scripts/equiv.py replay --all`, or, if the "
                      f"difference is intended, put it on the record:"
                      f'\n    python3 scripts/equiv.py accept "<trace name>" --reason "..."'
                      f"\n  Accepting does not make the trace green. It makes it explained, which is all this "
                      f"gate asks of anything else that is still imperfect.", file=sys.stderr)
                return 1
            print(f"Equivalence: {len(failing)} red trace(s) in {runs[0]['path']}, all named in "
                  f"parity/equiv/DECISIONS.md. Locking.")
    return None


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
    for check, which in ((_lock_gate4_checks, "gate-4"), (_lock_gate3_checks, "gate-3"), (_lock_gate5_checks, "gate-5")):
        if gid == which:
            rc = check(gid)
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
    # Absent directories contribute no files and no hashes, so a project with no Rule Cards
    # locks exactly as it did before — the line appears in the lock file and protects an
    # empty set, which is the correct description of that project.
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
    print('Usage: gate.py status | lock <gate-id> [--by <name>] | reopen <gate-id> --reason "..."', file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
