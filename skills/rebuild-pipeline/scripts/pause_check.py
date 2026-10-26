#!/usr/bin/env python3
"""pause_check.py — is it safe to pause the rebuild pipeline and resume in a new session?
Run from the workbench root.

Usage:
  python3 scripts/pause_check.py

This is NOT one of the pipeline's five hash-pinned gates (gate-1..gate-5) — it locks
nothing and has no protects:/PreToolUse enforcement. It's a repeatable, advisory readiness
check: git cleanliness across the workbench and every repo in repos.yaml, whether that work
has actually left the machine (a remote exists; no unpushed commits — including on a
detached HEAD — no unpushed tags, no stash entries), any gate left mid-decision (reopened
but not re-locked), AC flow assertions left unlocked, shipped slices with no slice review,
code repos missing their `.rebuild-workbench` marker while a slice is in progress,
docker-compose stacks left running,
and host-native dev servers (pnpm dev, go run, etc.) left running. Exits 0 always; "unsafe"
is communicated in the report, not a process-failure exit code, since nothing here should
ever block a tool call the way the gate-guard hook does.

It is a script and not a line in a doc because the answer is a dozen separate git and process
questions across every repo, asked the same way every time — a checklist in prose gets
skimmed, and the one question skipped is the one whose work is lost.
Zero-dependency: repos.yaml is parsed with the same fixed-subset regex style as gate.py.
"""

import math
import os
import re
import subprocess
import sys

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def _read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


LOCKS = "locks"
ORDER = ["gate-1", "gate-2", "gate-3", "gate-4", "gate-5"]

# JS String.prototype.trim: not Python's str.strip, which also strips \x1c-\x1f and \x85.
_JS_WS = " \t\n\v\f\r           " \
         "      　﻿"


def _trim(s):
    return s.strip(_JS_WS)


def _js_round(x):
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


# Runs a command and returns its trimmed stdout; raises on a non-zero exit or a missing binary,
# which every caller treats as "this answer is unavailable". `quiet` mirrors the Node original's
# stdio: with it stderr is captured and dropped; without it git's own stderr reaches ours, so a
# real failure is visible to the person running the check.
def _out(args, cwd=None, quiet=False, timeout=None, env=None):
    r = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE if quiet else None, text=True, encoding="utf-8",
                       errors="replace", check=True, timeout=timeout, env=env)
    return _trim(r.stdout)


_FAILED = (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError)


# Shell-quote a path for the remediation commands printed below. `repos.yaml` only forbids
# spaces in the *relative* path, and resolve() prepends the workbench's parent directory,
# which is nobody's choice and routinely contains one (`My Drive`, `Mobile Documents`). An
# unquoted `-C /…/My Drive/code` hands the user a command that dies on
# `cannot change to '/…/My'` — i.e. tells them work is unpushed and gives them no way to push it.
def _shq(p):
    if re.fullmatch(r"[A-Za-z0-9@%+=:,./_-]+", p):
        return p
    return "'" + p.replace("'", "'\\''") + "'"


# --- 1. Git cleanliness: workbench + every repo in repos.yaml ---
def _is_git_repo(d):
    try:
        _out(["git", "rev-parse", "--is-inside-work-tree"], cwd=d, quiet=True)
        return True
    except _FAILED:
        return False


def _git_dirty(d):
    try:
        return _out(["git", "status", "--porcelain"], cwd=d)
    except _FAILED:
        return None  # not a git repo, or git unavailable


# A commit is not durable just because it exists. "Safe to pause" has to mean the work
# survives the machine, so this also asks whether each repo has a remote and whether
# anything is sitting on a local ref no remote has seen.
def _has_origin(d):
    try:
        _out(["git", "remote", "get-url", "origin"], cwd=d, quiet=True)
        return True
    except _FAILED:
        return False


# Which refs this walk names is the whole design, and every inclusion and exclusion here is
# load-bearing:
#   - `--branches` alone walks refs/heads only, so a commit made on a DETACHED HEAD is
#     invisible and the repo reports as fully pushed. Not exotic here — gate.py hands out
#     `git checkout --detach <gate-tag>` for submodule syncing, so this pipeline actively
#     puts people in that state. Hence the explicit HEAD.
#   - `--all` would over-reach the other way: it includes refs/stash, and a stash cannot be
#     pushed by any `git push`, so counting it here produces a warning whose suggested fix
#     does nothing and which therefore never clears. Stashes are real risk, but they are a
#     different problem with a different remedy — counted separately below.
#   - `--tags` is left out for that same never-clears reason, which is easy to get wrong:
#     the exclusion set `--not --remotes` covers refs/remotes/* — remote-tracking BRANCHES —
#     and pushing a tag creates no remote-tracking ref at all. So a gate tag that IS on
#     origin (on a commit no surviving branch reaches, exactly what a reopen or a
#     squash-merge leaves behind) would contribute to this count on every future run with no
#     command that ever clears it. Tags are compared by name against the remote instead
#     (_unpushed_tags, below), and pushing an unpushed tag carries its commits with it, so
#     dropping `--tags` here loses no coverage.
# HEAD is verified before being named, rather than trusted: on an unborn HEAD (a fresh repo,
# or `git checkout --orphan`) naming it makes git abort with "ambiguous argument 'HEAD'",
# which would take the whole walk down and turn real unpushed commits into an indeterminate
# result — the failure direction that matters here.
def _unpushed_count(d):
    refs = ["--branches"]
    try:
        _out(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=d, quiet=True)
        refs.append("HEAD")
    except _FAILED:
        pass  # unborn HEAD — there is no HEAD commit to name, and --branches still walks
    try:
        out = _out(["git", "log", *refs, "--not", "--remotes", "--oneline"], cwd=d, quiet=True)
        return len([l for l in out.split("\n") if l]) if out else 0
    except _FAILED:
        return None


# A stash is local-only by construction: it lives at refs/stash, no push sends it, and it
# survives neither a dead disk nor a fresh clone. Easy to leave behind precisely because
# `git status` then reports the tree as clean.
def _stash_count(d):
    try:
        out = _out(["git", "stash", "list"], cwd=d)
        return len([l for l in out.split("\n") if l]) if out else 0
    except _FAILED:
        return 0


# Detached HEAD changes the remedy, not just the count: plain `git push` fails with
# "You are not currently on a branch", so the message has to say to land it somewhere first.
def _detached_head(d):
    try:
        _out(["git", "symbolic-ref", "-q", "HEAD"], cwd=d, quiet=True)
        return False
    except _FAILED:
        return True


# ...and a detached HEAD *mid-rebase* changes it again. A conflicted rebase is the most
# ordinary way a session ends detached, and there `git switch -c <branch>` does not work at
# all: git answers `fatal: cannot switch branch while rebasing`. Printing a command that
# cannot run in the state being reported is the same dead end this check exists to remove, so
# detect the in-progress operation and give advice that works while it is running
# (`git branch <name>` records the current HEAD without touching the rebase).
def _in_progress_op(d):
    for rel, name in [
        ("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
        ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect"),
    ]:
        try:
            # --git-path resolves the layout (worktrees, separate git dirs) and returns a path
            # relative to the repo's cwd, so it has to be resolved against dir before testing.
            p = _out(["git", "rev-parse", "--git-path", rel], cwd=d)
            if p and os.path.exists(os.path.abspath(os.path.join(d, p))):
                return name
        except _FAILED:
            pass  # try the next marker
    return None


# Tags are refs, not commits, so the walk above structurally cannot see them: a gate tag
# pointing at an already-pushed commit is itself still local-only. It matters because code
# repos pin the workbench as a submodule at `gate-N/vN` — a tag that never left the machine
# breaks `git clone --recurse-submodules` for everyone but you.
# The only way to know is to ask the remote, so this is the one networked check here:
# GIT_TERMINAL_PROMPT=0 and a short timeout keep it from ever hanging a session-end check,
# and it returns None (→ a note, not a blocking issue) whenever the remote can't be reached.
def _unpushed_tags(d):
    try:
        local = _out(["git", "tag"], cwd=d)
    except _FAILED:
        return None
    if not local:
        return []
    try:
        remote = _out(["git", "ls-remote", "--tags", "origin"], cwd=d, quiet=True, timeout=5,
                      env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        # Peeled annotated tags appear twice, as `<sha> refs/tags/x` and `refs/tags/x^{}`.
        on_remote = {m.group(1) for m in re.finditer(r"refs/tags/(.+?)(?:\^\{\})?$", remote, re.M)}
        return [t for t in local.split("\n") if t and t not in on_remote]
    except _FAILED:
        return None


class _Report:
    def __init__(self):
        self.issues = []
        self.notes = []
        # Set whenever a durability question could not be answered (a remote was unreachable). The
        # final verdict has to weaken when this is true: "all work pushed to a remote" is a claim,
        # and an indeterminate check does not support it.
        self.unverified = False


def _check_repo(rep, label, d):
    # A registered path that does not exist is a misconfiguration, not a benign absence: the
    # repo is listed as covered and nothing about it is actually checked, silently, for the rest
    # of the project. A one-character typo in `path:` is enough. That is an issue, not a note.
    if not os.path.exists(d):
        rep.issues.append(f"{label}: registered in repos.yaml but this path does not exist ({d}) — "
                          "nothing about this repo was checked. Fix its `path:` (relative to the workbench root) "
                          "or remove the entry; a repo that is silently uncovered is worse than one that is absent.")
        return
    if not _is_git_repo(d):
        rep.notes.append(f"{label}: not a git repo — skipped.")
        return
    dirty = _git_dirty(d)
    if dirty is None:
        rep.notes.append(f"{label}: git unavailable — skipped.")
        return
    if dirty:
        rep.issues.append(f"{label}: {len(dirty.split(chr(10)))} uncommitted change(s) — {d}")
    else:
        rep.notes.append(f"{label}: clean.")

    at = "" if d == "." else f" -C {_shq(d)}"

    # Stashes are local-only whether or not a remote exists, so this has to run BEFORE the
    # no-remote bail-out below rather than after it. A repo still waiting for its remote is
    # exactly where stashed work hides, and the user's next move there is the printed
    # `gh repo create --push`, which succeeds and ends the session — the stash never gets
    # mentioned to anyone, because `git status` calls the tree clean.
    stashes = _stash_count(d)
    if stashes:
        rep.issues.append(f"{label}: {stashes} stash entr{'y' if stashes == 1 else 'ies'} — a stash is "
                          f"local-only and no push sends it, so this work dies with the machine ({d}). "
                          f"Review `git{at} stash list`, then pop and commit what matters or drop what doesn't.")

    if not _has_origin(d):
        rep.issues.append(f"{label}: no git remote — every commit, branch and tag here exists only on "
                          f"this machine ({d}). Give it one: `gh repo create <name> --private --source . --push` "
                          "(visibility follows license-posture.md), then re-run this check — with no remote to "
                          "compare against, nothing below could be established.")
        return
    stale_tags = _unpushed_tags(d)
    if stale_tags is None:
        rep.unverified = True
        rep.notes.append(f"{label}: could not reach origin to check tags — if you locked a gate this "
                         f"session, confirm `git{at} push --tags` landed.")
    elif stale_tags:
        shown = ", ".join(stale_tags[:3]) + (", …" if len(stale_tags) > 3 else "")
        rep.issues.append(f"{label}: {len(stale_tags)} tag(s) not on the remote ({shown}) — "
                          f"`git{at} push --tags`. Code repos pin the workbench at gate tags, so an unpushed "
                          "one breaks a fresh recursive clone.")

    ahead = _unpushed_count(d)
    # This walk reads local refs only, so reaching git at all is enough to answer it — a failure
    # here is unexplained rather than expected, and "we could not tell" must not read as "fine".
    if ahead is None:
        rep.issues.append(f"{label}: could not determine whether this repo's commits have left the "
                          f"machine ({d}) — the ref walk failed. Check by hand: "
                          f"`git{at} log --branches HEAD --not --remotes --oneline`.")
        return
    if ahead > 0:
        op = _in_progress_op(d) if _detached_head(d) else None
        if op:
            # Mid-rebase/cherry-pick: `git switch` refuses outright, `git branch` does not.
            rep.issues.append(
                f"{label}: {ahead} commit(s) not on any remote, and a {op} is in progress with HEAD "
                f"detached ({d}). `git switch` refuses mid-{op}, so either finish or abort it "
                f"(`git{at} {op} --continue` / `--abort`) and push after, or park the current HEAD "
                f"without disturbing it: `git{at} branch wip/<name>` then "
                f"`git{at} push origin wip/<name>`.")
        elif _detached_head(d):
            rep.issues.append(
                f"{label}: {ahead} commit(s) not on any remote, and HEAD is DETACHED — they are on "
                f"no branch, so a plain push will not send them ({d}). Land them first: "
                f"`git{at} switch -c <branch>` then `git{at} push -u origin <branch>`.")
        else:
            # Not `git push`: this count spans every local branch, and a bare push sends only the
            # current one — or fails outright when it has no upstream, which every fresh slice
            # branch lacks. Either way the user is told the work is off-machine when it is not.
            rep.issues.append(
                f"{label}: {ahead} commit(s) not on any remote — `git{at} push --all origin` "
                "(a bare `git push` sends only the current branch, and nothing at all if it has no "
                "upstream; this count covers every local branch).")
    else:
        rep.notes.append(f"{label}: pushed to origin.")


def _slices_in_progress():
    try:
        block = re.search(r"^slices:\n((?:(?:[ \t]+.*)?\n)*)", _read_text(os.path.join("plan", "progress.yaml")), re.M)
        if not block:
            return []
        return [m.group(1) for m in re.finditer(r"^\s+(S[0-9]+):\s*([a-z-]+)", block.group(1), re.M)
                if m.group(2) == "in-progress"]
    except OSError:
        return []


# unquote mirrors gate.py's yaml_str/unquote — title may have been quoted there
# (e.g. it contains ": ") and must be unescaped the same way when read back here.
def _unquote(s):
    if s is not None and re.fullmatch(r'".*"', s):
        return s[1:-1].replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
    return s


def _parse_lock(lock_id):
    p = os.path.join(LOCKS, f"{lock_id}.yaml")
    if not os.path.exists(p):
        return None
    text = _read_text(p)

    def get(k):
        m = re.search(rf"^{k}: (.*)$", text, re.M)
        return _unquote(_trim(m.group(1))) if m else None
    hm = re.search(r"history:[\s\S]*$", text)
    history_block = hm.group(0) if hm else ""
    actions = [m.group(1) for m in re.finditer(r"^\s*-\s*action:\s*(\S+)", history_block, re.M)]
    return {"id": lock_id, "title": get("title"), "status": get("status"),
            "lastAction": actions[-1] if actions else None}


# A NOTE, never an issue, and that is a deliberate choice rather than an oversight: the slice
# review is advisory by design. It locks nothing and blocks nothing, so it must not be able to
# turn a session end "unsafe" — a check that cries wolf about a report nobody is required to run
# is a check that gets ignored, taking the real warnings with it.
#
# Read from plan/progress.yaml only, which is where g6-parity.md says slice completion is
# recorded ("never in the gate-locked plan/slices.yaml"). Parsed with the same fixed-subset
# regex style as the rest of this file — it stays zero-dependency because it must run in a
# workbench with no YAML parser to hand. `notes:` is keyed by slice id too, so the
# scan is scoped to the `slices:` block rather than matching S-ids anywhere in the file.
def _progress_slice_statuses():
    p = os.path.join("plan", "progress.yaml")
    if not os.path.exists(p):
        return None
    try:
        lines = _read_text(p).split("\n")
    except OSError:
        return None
    i = next((k for k, l in enumerate(lines) if re.match(r"^slices:", l)), -1)
    if i == -1:
        return {}
    out = {}
    inline = _trim(lines[i][lines[i].index(":") + 1:])
    if inline.startswith("{"):
        # Flow mapping — `slices: { S1: deployed }` is the shape g6-parity.md itself shows, and it
        # may wrap. Accumulate until the closing brace rather than assuming one line.
        buf = inline
        j = i
        while "}" not in buf and j + 1 < len(lines):
            buf += " " + _trim(lines[j + 1])
            j += 1
        for m in re.finditer(r"(S[0-9]+)\s*:\s*([A-Za-z-]+)", buf):
            out[m.group(1)] = m.group(2)
        return out
    for j in range(i + 1, len(lines)):
        if re.match(r"^\S", lines[j]):
            break  # back to column 0 — a different top-level key
        m = re.match(r"^\s+(S[0-9]+)\s*:\s*(\S+)", lines[j])
        if m:
            out[m.group(1)] = re.sub(r"[\"']", "", m.group(2))
    return out


# A NOTE, never an issue: nothing breaks. The cost is tokens — an orchestrator that Reads a
# state file whole carries it in context, and re-reads it from cache on every later turn. A
# 360 KB backlog is ~90k tokens paid again per turn for the rest of the session. The remedy is
# to read by heading or line range, not to delete history, so that is what the note says.
STATE_FILE_LIMIT = 40 * 1024


def _check_compose(rep, label, d):
    if not os.path.exists(os.path.join(d, "docker-compose.yml")):
        return
    try:
        out = _out(["docker", "compose", "ps", "--format", "{{.Name}}\t{{.State}}"], cwd=d, quiet=True)
        if not out:
            rep.notes.append(f"{label}: docker-compose.yml present, nothing running.")
            return
        running = [l for l in out.split("\n") if re.search(r"running", l, re.I)]
        if running:
            rep.issues.append(f"{label}: {len(running)} container(s) still running (docker compose ps) — {d}")
        else:
            rep.notes.append(f"{label}: docker-compose.yml present, containers stopped.")
    except _FAILED:
        rep.notes.append(f"{label}: docker-compose.yml present, but docker is unavailable/not running — could not check.")


# Port/command conventions vary per repo, so this doesn't guess either — it looks for any
# running process whose command line references the repo's own absolute path (true for
# `pnpm dev`/`nuxt dev`/`go run` alike, since node_modules/.bin, cli entrypoints, or the
# working directory itself all resolve under it).
def _check_dev_process(rep, label, d):
    absd = os.path.abspath(d)
    escaped = re.sub(r"[.*+?^${}()|\[\]\\]", lambda m: "\\" + m.group(0), absd)
    # pgrep -f is an UNANCHORED regex match, so the bare path also matches any sibling that
    # merely extends it: `/x/foo` matches `/x/foo.git`, `/x/foo-copy`, `/x/foobar`. That
    # reported a dev server in repos that had none — the likeliest false match being the
    # repo's own bare remote (`<repo>.git`) sitting next to it.
    # Require a path boundary: the next character must open a child path, be whitespace (the
    # path was the whole argument), or end the command line.
    # Passed as an argument, not through a shell line: the Node original's double-quoted shell
    # string turned `\$` and `\\` in an escaped path into bare `$` and `\`.
    try:
        r = subprocess.run(["pgrep", "-f", f"{escaped}(/|[[:space:]]|$)"], stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                           errors="replace")
    except OSError:
        rep.notes.append(f"{label}: could not check for running processes (pgrep unavailable).")
        return
    if r.returncode == 0:
        pids = [l for l in _trim(r.stdout).split("\n") if l]
        if pids:
            rep.issues.append(f"{label}: {len(pids)} process(es) still running under {absd} (e.g. a dev server) — pid(s) {', '.join(pids)}")
        else:
            rep.notes.append(f"{label}: no host-native process running.")
    elif r.returncode == 1:
        rep.notes.append(f"{label}: no host-native process running.")
    else:
        rep.notes.append(f"{label}: could not check for running processes (pgrep unavailable).")


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if not os.path.exists(os.path.join(LOCKS, "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1

    rep = _Report()
    issues, notes = rep.issues, rep.notes

    _check_repo(rep, "workbench", ".")

    repo_entries = []
    if os.path.exists("repos.yaml"):
        text = _read_text("repos.yaml")
        # Two supported shapes: `repos: []` (empty stub) or a `- path: ...` / `- name: ... path: ...` list.
        repo_entries = [{"name": m.group(1) or m.group(2), "path": m.group(2)}
                        for m in re.finditer(r"^\s*-\s*(?:name:\s*(\S+)\s*)?path:\s*(\S+)", text, re.M)]
    if not repo_entries:
        notes.append("repos.yaml has no repo entries — nothing outside the workbench was checked. "
                     "If code repos exist for this project, add them (see repos.yaml's own comment for the format).")
    for e in repo_entries:
        _check_repo(rep, e["name"], os.path.abspath(e["path"]))

    # --- 1b. Code repos whose `.rebuild-workbench` marker is missing or wrong, mid-slice ---
    # runbook_guard.py finds the live workbench through this marker and fails open without it, so a
    # repo created before the marker step existed had the guard off for its whole life, and nothing
    # said so; it was found by reading the repo checklist. Only while a slice is in progress, which
    # is when the guard has anything to guard. lanes_check.py carries the same check, copied, not
    # imported — if you change one, change both.
    in_progress = _slices_in_progress()
    if in_progress:
        here = os.path.realpath(".")
        for e in repo_entries:
            name = e["name"]
            d = os.path.abspath(e["path"])
            if not os.path.exists(d):
                continue  # already an issue above
            target = ""
            try:
                target = next((l for l in (_trim(l) for l in _read_text(os.path.join(d, ".rebuild-workbench")).split("\n"))
                               if l and not l.startswith("#")), "")
            except OSError:
                pass  # missing
            points = os.path.abspath(os.path.join(d, target)) if target else ""
            fix = (f"Fix: `cd {_shq(d)} && echo {_shq(here)} > .rebuild-workbench && git add .rebuild-workbench && "
                   'git commit -m "chore: point at the rebuild workbench"` (g5-first-slice.md, repo checklist step 5).')
            if not target:
                issues.append(f"{name}: no `.rebuild-workbench` marker while {', '.join(in_progress)} is in progress, "
                              f"so runbook_guard.py is off for this repo (it fails open without one). {fix}")
            elif not os.path.exists(os.path.join(points, "locks", "pipeline.yaml")) or os.path.realpath(points) != here:
                issues.append(f"{name}: `.rebuild-workbench` points at {points}, not this workbench, so runbook_guard.py "
                              f"reads the wrong progress file or none. {fix}")

    # --- 2. Gates left mid-decision: reopened but not re-locked ---
    for gate_id in ORDER:
        l = _parse_lock(gate_id)
        if not l:
            continue
        if l["status"] == "open" and l["lastAction"] == "reopened":
            title = "undefined" if l["title"] is None else l["title"]
            issues.append(f"{gate_id} ({title}): reopened but not re-locked — a decision is mid-flight.")
        elif l["status"] == "locked":
            notes.append(f"{gate_id}: locked.")
        else:
            notes.append(f"{gate_id}: open (not yet reached — normal mid-pipeline state).")

    # --- 2b. AC flow assertions left unlocked ---
    # `flows.py unlock` suspends the PreToolUse guard on parity/flows/ for one deliberate
    # assertion change. Left on, the guard is simply off — and the next agent to hit a red build
    # can loosen an assertion with nothing noticing. Same category as a reopened gate: a decision
    # mid-flight, safe for an hour and not safe to sleep on.
    unlock_file = os.path.join("parity", "flows", ".unlocked.yaml")
    if os.path.exists(unlock_file):
        text = _read_text(unlock_file)

        def get(k):
            m = re.search(rf"^{k}:\s*(.*)$", text, re.M)
            return re.sub(r'^"|"$', "", _trim(m.group(1))) if m else None
        issues.append(f"parity/flows: AC flow assertions still UNLOCKED (since {get('at') or '?'}, "
                      f"by {get('by') or '?'}: {get('reason') or 'no reason recorded'}) — the guard is off. "
                      "Re-lock with `python3 scripts/flows.py relock`.")
    elif os.path.exists(os.path.join("parity", "flows")):
        notes.append("parity/flows: AC flow assertions protected.")

    # --- 2c. Shipped slices with no slice review ---
    slice_statuses = _progress_slice_statuses()
    if slice_statuses is not None:
        shipped = [sid for sid, st in slice_statuses.items() if st in ("done", "deployed")]
        unreviewed = [sid for sid in shipped if not os.path.exists(os.path.join("plan", "slice-reviews", f"{sid}.md"))]
        if unreviewed:
            notes.append(f"slice reviews: {', '.join(unreviewed)} shipped without one — "
                         f"`python3 scripts/slice_review.py {unreviewed[0]}`. Advisory: this does not make it unsafe to pause, "
                         "but a boundary is the cheap moment to change the plan and it is about to pass.")
        elif shipped:
            notes.append(f"slice reviews: all {len(shipped)} shipped slice(s) have one.")

    # --- 2d. Oversized plan/ state files ---
    for f in ["plan/backlog.md", "plan/progress.yaml", "plan/slices.yaml"]:
        try:
            size = os.stat(f).st_size
        except OSError:
            continue
        if size > STATE_FILE_LIMIT:
            hint = "`grep -n '^## ' " + f + "`" if f.endswith(".md") else "`grep -n '^  S[0-9]*:' " + f + "`"
            notes.append(f"{f}: {_js_round(size / 1024)} KB (~{_js_round(size / 4000)}k tokens). Never Read it whole — "
                         f"{hint} for an index, then Read with offset/limit.")

    # --- 3. Running docker-compose stacks left up ---
    _check_compose(rep, "workbench", ".")
    for e in repo_entries:
        _check_compose(rep, e["name"], os.path.abspath(e["path"]))

    # --- 4. Host-native dev servers left running (pnpm dev, go run, etc.) ---
    for e in repo_entries:
        _check_dev_process(rep, e["name"], os.path.abspath(e["path"]))

    # --- Report ---
    print("Pause-safety check\n")
    for n in notes:
        print(f"  {n}")
    if issues:
        print("\n⚠️  NOT safe to pause without a look — issues found:")
        for i in issues:
            print(f"  - {i}")
        print("\nCommit/persist draft work, push it off-machine, "
              "resolve any reopened gate (re-lock or explicitly leave it open with the reason noted to "
              "the user), and stop or consciously keep running services before ending the session.")
    elif rep.unverified:
        # Only the tag comparison needs the network, and it degrades to a note so a dead VPN never
        # blocks a session end. But the verdict cannot keep asserting what that note failed to
        # establish: local `refs/remotes/*` survive going offline, so a gate tag that was never
        # pushed looks identical here to one that was.
        print("\n🟡 Safe to pause as far as could be checked — git clean everywhere checked, "
              "no unpushed commits, no gate mid-decision, no services left running.\n"
              "   But a remote was unreachable, so unpushed TAGS could not be ruled out (see the notes "
              "above). If you locked a gate this session, confirm `git push --tags` landed once you are "
              "back online — a gate tag that never left the machine breaks every code repo pinning it.")
    else:
        print("\n✅ Safe to pause — git clean everywhere checked, all work pushed to a remote, "
              "no gate mid-decision, no services left running.")
    print("\nReminder (not scriptable): confirm nothing non-trivial exists only in this "
          "conversation — a partial ADR, a draft matrix, in-flight findings — that hasn't reached disk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
