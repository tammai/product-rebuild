#!/usr/bin/env python3
"""holdout.py — hidden tests (spec 05 P4, decision D4). Run from the workbench root.

  python3 scripts/holdout.py split [--seed <n>]                 # after rspec:check, before gate.py lock gate-4
  python3 scripts/holdout.py reconcile                          # after any rspec:verify (lane_plan, boundary, gate run it)
  python3 scripts/holdout.py run <Sn> [--repo <code repo>] [--contracts <contracts.py>]
                                                                 # at G6, with ACCEPT_BASE_URL set to the slice build

WHY HIDDEN TESTS. Every test a builder can see is one it can build to: a lane whose suite passes has
shown the build agrees with the tests it read, not that it does what the reference does. A share of
the recorded tests the lanes never see measures the second thing. D4: 25% of each slice's level 2
tests (recorded against the reference, contracts C3), at least one per feature with three or more
criteria, chosen from a seed recorded at the Gate 4 lock so anyone can re-derive the list.

SPLIT moves the chosen files out of `docs/acceptance/` into a git repo in a per-user data folder
(`%LOCALAPPDATA%/product-rebuild/holdouts/<project>-<random>`, or under $XDG_DATA_HOME, or
$PRODUCT_REBUILD_DATA), named only in that folder's `holdouts.json`: never in the workbench, a lane brief
or the project parent, so no lane is handed its path (redesign R1; P4's sibling repo was one `cd ..` from
every lane). It is never a submodule of any code repo (the split refuses when a repo listed in repos.yaml
contains or references it), marks them `visibility: hidden` in the workbench manifest (contracts C4
leaves this to product-rebuild), and writes `plan/holdout.json`. It runs before the gate-4 lock, not
after: the lock hashes the manifest and records the seed and list hash, and gate.py refuses gate-4
until that record matches the manifest. Level 2 already excludes flaky tests (rspec's verify keeps a
criterion with a pass and a failure at level 1), so flaky ones are never hidden (06, Risks).

RECONCILE puts the hidden entries back after rspec:verify rebuilds the manifest without them (rspec has no
notion of a hidden test, and no rspec change is wanted for one), from the copy the split kept in the
holdout repo, and re-pins the record's manifest hash so gate-4 can relock. Re-pinning is decided (coordinator,
M-2): every manifest change after the split passes through reconcile, so gate-4's "manifest changed after the
split" refusal fires only when reconcile refuses (a hidden criterion open again, a hidden file changed, the
holdout not found). The seed and list hash stay as the split drew them.

RUN reports per criterion, never with test content: a failure says what the build did (`HTTP status
500`, `/key was "X"`), never what the test wanted, because a report a lane reads must not turn a hidden
test into an open one. A test that cannot run is `not run: <reason>` and fails the run (design rule
6). HTTP tests go through `contracts.py run-http`; Playwright through the code repo's own
`@playwright/test` by path (npx can fetch a different version than the repo locks); Maestro through
`maestro test`; the cli format is not settled in contracts v1, so a cli test is not run.

Standard library only; vendored into each workbench and run alone, so its helpers are copies.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys

SPEC = "docs"
BUNDLE = os.path.join(SPEC, "acceptance")
MANIFEST = os.path.join(BUNDLE, "manifest.json")
RECORD = os.path.join("plan", "holdout.json")
HIDDEN = "hidden.json"  # in the holdout folder: the hidden manifest entries the split moved
SHARE = 0.25          # D4
MIN_CRITERIA = 3      # D4: a feature with at least this many criteria gets at least one hidden test
SLICE_RE = re.compile(r"^##\s*Slice\s+(\d+)\s*:?\s*(.*)$", re.M)  # rspec_lib.SLICE_RE; change both together


def read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        return re.sub(r"\r\n?", "\n", fh.read())


def die(msg):
    print(f"holdout: {msg}", file=sys.stderr)
    return 1


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def sha256_file(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def slices():
    """{"S<n>": [feature IDs]} from rspec's build-plan.md, as rspec's build_slices reads it."""
    p = os.path.join(SPEC, "build-plan.md")
    text = read_text(p) if os.path.exists(p) else ""
    heads = list(SLICE_RE.finditer(text))
    out = {}
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        out[f"S{h.group(1)}"] = list(dict.fromkeys(re.findall(r"\bF-[A-Z][A-Z0-9]*-\d+\b", body)))
    return out


def load_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


# The per-user data folder and its local config, copied from hooks/scripts/hooklib.py (rebuild_data_dir,
# holdout_config) because this script runs alone in a workbench; change both together. The hidden tests live
# there, never in the project parent, so no lane is handed their path (spec 05 P4, redesign R1).
HOLDOUT_CONFIG = "holdouts.json"


def rebuild_data_dir():
    env = os.environ.get("PRODUCT_REBUILD_DATA")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "product-rebuild")


def holdout_config():
    try:
        data = load_json(os.path.join(rebuild_data_dir(), HOLDOUT_CONFIG))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str) and v} if isinstance(data, dict) else {}


def _workbench_key():
    return os.path.normcase(os.path.realpath(os.getcwd()))


def holdout_dir():
    """This workbench's holdout folder from the local config, or None before the split has made one."""
    return holdout_config().get(_workbench_key())


def new_holdout_dir():
    """A fresh holdout folder under the data folder, recorded in the local config. The random suffix keeps its
    name unguessable, so a lane cannot spell it without having been told it."""
    import secrets
    project = None
    p = os.path.join("locks", "pipeline.yaml")
    if os.path.exists(p):
        m = re.search(r"^project:[ \t]*(\S+)", read_text(p), re.M)
        project = m.group(1).strip("\"'") if m else None
    project = re.sub(r"[^A-Za-z0-9._-]", "-", project or re.sub(r"-workbench\Z", "", os.path.basename(os.getcwd())))
    data = rebuild_data_dir()
    hold = os.path.join(data, "holdouts", f"{project}-{secrets.token_hex(6)}")
    cfg = holdout_config()
    cfg[_workbench_key()] = hold
    write_atomic(os.path.join(data, HOLDOUT_CONFIG), json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    return hold


def listed_repos():
    p = "repos.yaml"
    if not os.path.exists(p):
        return []
    out = []
    for m in re.finditer(r"^\s*-\s*(?:name:\s*(\S+)\s*)?path:\s*(\S+)", read_text(p), re.M):
        out.append(os.path.abspath(m.group(2)))
    return out


def exposure(hold):
    """Listed code repos that contain the holdout or reference it in .gitmodules (P4: never a submodule)."""
    if not hold:
        return []  # no split yet: nothing hidden to expose
    bad = []
    real = os.path.normcase(os.path.realpath(hold))
    name = os.path.basename(hold)
    for repo in listed_repos():
        r = os.path.normcase(os.path.realpath(repo))
        gm = os.path.join(repo, ".gitmodules")
        if real == r or real.startswith(r.rstrip(os.sep) + os.sep):
            bad.append(f"{repo} contains it")
        elif os.path.exists(gm) and re.search(rf"(^|[/\\\s=]){re.escape(name)}(\.git)?\s*$", read_text(gm), re.M):
            bad.append(f"{repo}/.gitmodules references it")
    return bad


def choose(seed, slice_map, lock, tests):
    """{slice: [criterion IDs]} per D4. Deterministic for a seed: candidates are sorted before any draw."""
    level = {c["id"]: c.get("level") for c in lock.get("criteria") or []}
    feature_of = {c["id"]: c.get("feature") for c in lock.get("criteria") or []}
    per_feature = {}
    for c in lock.get("criteria") or []:
        if c.get("priority") != "Drop":
            per_feature[c.get("feature")] = per_feature.get(c.get("feature"), 0) + 1
    rng = random.Random(seed)
    out = {}
    for sid in sorted(slice_map, key=lambda s: int(s[1:])):
        feats = slice_map[sid]
        cands = sorted({t["criterion"] for t in tests
                       if t.get("visibility", "open") == "open" and level.get(t["criterion"]) == 2
                       and feature_of.get(t["criterion"]) in feats})
        by_feat = {}
        for c in cands:
            by_feat.setdefault(feature_of[c], []).append(c)
        picked = []
        for f in sorted(by_feat):
            if per_feature.get(f, 0) >= MIN_CRITERIA:
                picked.append(rng.choice(by_feat[f]))
        target = max(math.ceil(SHARE * len(cands)), len(picked))
        pools = {f: [c for c in sorted(by_feat[f]) if c not in picked] for f in sorted(by_feat)}
        for pool in pools.values():
            rng.shuffle(pool)
        order = sorted(pools)
        rng.shuffle(order)
        while len(picked) < target and any(pools.values()):
            for f in order:
                if pools[f] and len(picked) < target:
                    picked.append(pools[f].pop())
        out[sid] = sorted(picked)
    return out


def list_sha256(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


IGNORE_LINES = ("# The bundle stays out of git until holdout.py split (05 P4): its hidden share must never be in",
                "# this repo's history, which every lane holds as a submodule. The split removes these lines.",
                "docs/acceptance/", "docs/verify/runs.jsonl")  # rebuild_init.py writes them; change both together
# rspec:verify logs every recording run here with run-http's failure message, which quotes the test's expected
# value ("got X, expected Y"): a hidden criterion's earlier failing runs would hand a lane its test.
RUNS = os.path.join(SPEC, "verify", "runs.jsonl")


def bundle_path(base, rel):
    """`base`/`rel` for a manifest `path`, or None when `rel` is absolute, has a drive or `..`, or resolves outside
    `base`. The manifest is agent-written data: an entry `../../p-holdout/...` once made a script copy a hidden
    test into a lane. lane_plan.py and boundary.py carry copies; change the three together."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or re.match(r"^[a-zA-Z]:", rel) \
            or ".." in re.split(r"[\\/]+", rel):
        return None
    p = os.path.join(base, rel)
    real_base = os.path.realpath(base)
    real = os.path.realpath(p)
    return p if real == real_base or real.startswith(real_base.rstrip(os.sep) + os.sep) else None


def write_atomic(p, text):
    """departures.write_atomic, copied because this script runs alone; change both together."""
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = f"{p}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def in_history(files, logs=()):
    """{path: [evidence]} for what the workbench's git already holds. A file in `files` counts when git has its
    content as an object, under any path, reachable or not: round 2 of the 3.0 review passed a path check
    with the reflog or a loose object a rewrite left behind. Both blob ids are tried, with and without the
    clean filters, since core.autocrlf makes them differ. A path in `logs` (rspec's verify log, which only
    grows, so its content never matches) counts when any commit on a ref or in the reflog held it. Empty
    outside git."""
    out = {}
    for rel in files:
        ids = {git(".", "hash-object", *flag, rel).stdout.strip() for flag in ((), ("--no-filters",))}
        held = sorted(i[:12] for i in ids if i and git(".", "cat-file", "-e", i).returncode == 0)
        if held:
            out[rel] = [f"object {i}" for i in held]
    for rel in logs:
        r = git(".", "log", "--all", "--reflog", "--format=%h", "--", rel.replace(os.sep, "/"))
        ids = r.stdout.split() if r.returncode == 0 else []
        if ids:
            out[rel] = ids
    return out


def unignore_bundle():
    if not os.path.exists(".gitignore"):
        return
    lines = read_text(".gitignore").split("\n")
    kept = [l for l in lines if l not in IGNORE_LINES]
    if kept != lines:
        write_atomic(".gitignore", "\n".join(kept))


def cmd_split(args):
    if os.path.exists(RECORD):
        return die(f"{RECORD} exists: the split already ran. Reopen gate-4 and remove it only if the user "
                   f"decides to re-draw the hidden tests.")
    for p in (MANIFEST, os.path.join(SPEC, "criteria.lock.json"), os.path.join(SPEC, "build-plan.md")):
        if not os.path.exists(p):
            return die(f"{p} is missing: run rspec through handoff and rspec:check first.")
    slice_map = slices()
    if not slice_map:
        return die(f"{SPEC}/build-plan.md has no `## Slice N:` section.")
    # A configured folder is reused: without RECORD no split finished, and its hidden.json is overwritten below.
    hold = holdout_dir() or new_holdout_dir()
    bad = exposure(hold)
    if bad:
        return die(f"the holdout repo {hold} would be reachable from a code repo: {'; '.join(bad)}. "
                   f"Hidden tests must never be in, or a submodule of, any code repo.")
    if "--seed" in args[:-1]:
        try:
            seed = int(args[args.index("--seed") + 1])
        except ValueError:
            return die("--seed takes a whole number.")
    else:
        seed = random.SystemRandom().randrange(2 ** 31)
    manifest = load_json(MANIFEST)
    tests = manifest.get("tests") or []
    chosen = choose(seed, slice_map, load_json(os.path.join(SPEC, "criteria.lock.json")), tests)
    hidden = sorted(c for ids in chosen.values() for c in ids)
    # Every test of a hidden criterion is hidden: a criterion can carry one test per runner, and one left
    # open would reach the lanes with the criterion it was meant to measure.
    moves = [t for t in tests if t.get("criterion") in set(hidden)]
    for t in moves:
        src = bundle_path(BUNDLE, t.get("path"))
        if not src:
            return die(f"the manifest path {t.get('path')!r} (a test for {t.get('criterion')}) leaves {BUNDLE}.")
        if not os.path.exists(src):
            return die(f"{src} (the test for {t['criterion']}) is missing.")
    seen = in_history([os.path.join(BUNDLE, t["path"]) for t in moves], [RUNS] if moves else [])
    if seen:
        return die("these tests the split would hide are already in the workbench's git history, which every lane "
                   "holds as a submodule: " + "; ".join(f"{p} in {', '.join(ids)}" for p, ids in sorted(seen.items()))
                   + ". The bundle's first commit must come after the split. Rewrite those commits out of the "
                   "history with the user (and from any remote), end with `git reflog expire --expire=now --all && "
                   "git gc --prune=now` so no unreachable copy is left, or re-record the bundle; then split again.")
    os.makedirs(hold, exist_ok=True)
    if not os.path.exists(os.path.join(hold, ".git")):
        r = git(hold, "init", "-q")
        if r.returncode:
            return die(f"git init in {hold} failed: {r.stderr.strip()}")
    for t in moves:
        dst = bundle_path(hold, t["path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(BUNDLE, t["path"]), dst)
        t["visibility"] = "hidden"
    if os.path.isdir(os.path.join(BUNDLE, "seed")):
        shutil.copytree(os.path.join(BUNDLE, "seed"), os.path.join(hold, "seed"), dirs_exist_ok=True)
    kept_runs = None
    if os.path.exists(RUNS):
        kept_runs, hidden_runs = [], []
        for line in read_text(RUNS).split("\n"):
            try:
                cid = json.loads(line).get("criterion") if line.strip() else None
            except (ValueError, AttributeError):
                cid = None
            # A line that does not parse may be anyone's, so it goes with the hidden ones.
            (hidden_runs if cid in set(hidden) or (line.strip() and cid is None) else kept_runs).append(line)
        if hidden_runs:
            write_atomic(os.path.join(hold, "verify", "runs.jsonl"), "\n".join(hidden_runs) + "\n")
    # The hidden entries as the split left them, for reconcile: rspec:verify rebuilds the workbench manifest
    # from its own records and drops them (it no longer has their files or runs).
    write_atomic(os.path.join(hold, HIDDEN), json.dumps({"tests": moves}, indent=2, ensure_ascii=False) + "\n")
    for step in (("add", "-A"), ("commit", "-q", "--allow-empty", "-m", f"holdout: {len(hidden)} hidden tests, seed {seed}")):
        r = git(hold, *step)
        if r.returncode:
            return die(f"git {step[0]} in {hold} failed, nothing in the workbench changed: "
                       f"{(r.stderr or r.stdout).strip()}")
    # The manifest and record go in by rename and the originals are removed last, so a crash leaves either the
    # old bundle (re-run the split) or a finished one, never hidden files missing with nothing recording where.
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    rec = {"seed": seed, "count": len(hidden), "list_sha256": list_sha256(hidden), "hidden": hidden,
           "slices": chosen, "manifest_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    write_atomic(MANIFEST, text)
    write_atomic(RECORD, json.dumps(rec, indent=2) + "\n")
    if kept_runs is not None:
        write_atomic(RUNS, "\n".join(l for l in kept_runs if l.strip()) + "\n")
    for t in moves:
        os.remove(os.path.join(BUNDLE, t["path"]))
    unignore_bundle()
    for sid, ids in chosen.items():
        print(f"{sid}: {len(ids)} hidden")
    print(f"{len(hidden)} hidden criteria ({len(moves)} tests) moved to the holdout repo (committed there, never "
          f"pushed by this script); seed {seed}. docs/acceptance/ is no longer ignored: commit the workbench now "
          f"(its first commit of the open bundle), then lock gate-2.")
    return 0


def reconcile():
    """(changed, error). Puts the split's hidden entries back into the workbench manifest after rspec:verify
    rebuilt it without them (every rspec:amend ends with one), and re-pins plan/holdout.json's manifest hash so
    gate-4 can relock. Without this the hidden suite reported every hidden criterion `not run` after an amend.
    Refuses, changing nothing, when a hidden criterion is open again in the workbench (a re-verify re-recorded
    its test) or a hidden file in the holdout folder changed since the split: either needs the user."""
    if not os.path.exists(RECORD):
        return False, None
    hold = holdout_dir()
    if not hold or not os.path.exists(os.path.join(hold, HIDDEN)):
        return False, (f"{RECORD} exists but the local config ({os.path.join(rebuild_data_dir(), HOLDOUT_CONFIG)}) "
                       f"names no holdout folder with {HIDDEN} for this workbench.")
    try:
        rec = load_json(RECORD)
        entries = load_json(os.path.join(hold, HIDDEN)).get("tests") or []
        manifest = load_json(MANIFEST)
    except (OSError, ValueError, AttributeError) as e:
        return False, f"{RECORD}, {MANIFEST} or the holdout's {HIDDEN} cannot be read: {e}"
    hidden = set(rec.get("hidden") or [])
    tests = manifest.get("tests") or []
    reopened = sorted({t.get("criterion") for t in tests if t.get("criterion") in hidden and t.get("visibility") != "hidden"}
                      | {e.get("criterion") for e in entries if os.path.exists(bundle_path(BUNDLE, e.get("path")) or "")})
    if reopened:
        return False, (f"hidden criteria are open again in {BUNDLE}: {', '.join(reopened)} (a re-verify re-recorded "
                       f"their tests). Lanes may now see them; ask the user whether to re-draw.")
    for e in entries:
        src = bundle_path(hold, e.get("path"))
        if not src or not os.path.exists(src) or sha256_file(src) != e.get("sha256"):
            return False, f"the hidden test for {e.get('criterion')} is missing or changed in the holdout folder since the split."
    have = {(t.get("criterion"), t.get("path")) for t in tests}
    missing = [e for e in entries if (e.get("criterion"), e.get("path")) not in have]
    if not missing and rec.get("manifest_sha256") == sha256_file(MANIFEST):
        return False, None
    if missing:
        write_atomic(MANIFEST, json.dumps({**manifest, "tests": tests + missing}, indent=2, ensure_ascii=False) + "\n")
    write_atomic(RECORD, json.dumps({**rec, "manifest_sha256": sha256_file(MANIFEST)}, indent=2) + "\n")
    return True, None


def cmd_reconcile():
    changed, err = reconcile()
    if err:
        return die(err)
    print(f"holdout: {'hidden entries restored and ' + RECORD + ' re-pinned; commit both' if changed else 'nothing to reconcile'}.")
    return 0


# ---------------------------------------------------------------- run

def _decoded(msg, at):
    try:
        return json.JSONDecoder().raw_decode(msg, at)[0]
    except ValueError:
        return None


def observed(msg):
    """(result, observed, pointer, value) from a run-http failure message: what the build did, never what the test
    wanted. The value is decoded as the JSON document it is, at the offset contracts.py puts it, because a regex
    over the message once ran into the expected value when it held the word `expected`. The observed text names
    no field (which field a hidden test checks is test content); `pointer` and `value` are for departure match
    rules only and are not written anywhere. Anything not recognised is withheld."""
    if msg.startswith("not run:"):
        return "not run", msg[len("not run:"):].strip(), None, None
    if msg.startswith("invalid test:"):
        return "not run", "the hidden test file does not parse", None, None
    m = re.search(r": status (\d+), expected \d+$", msg)
    if m:
        return "fail", f"HTTP status {m.group(1)}", "status", int(m.group(1))
    for pat, what in ((r" (/\S*): got ", "a field the test checks was {0}"),
                      (r" (/\S*): ", "a field the test checks was {0}, which breaks the test's rule")):
        m = re.search(pat, msg)
        if m and (pat.endswith("got ") or re.search(r" does not satisfy rule ", msg)):
            value = _decoded(msg, m.end())
            if value is not None or msg[m.end():].startswith("null"):
                return "fail", what.format(json.dumps(value, ensure_ascii=False)), m.group(1), value
    m = re.search(r" (/\S*): not present in the response$", msg)
    if m:
        return "fail", "a field the test checks is not in the response", m.group(1), None
    if re.search(r": response is not JSON$", msg):
        return "fail", "the response is not JSON", None, None
    m = re.search(r": request failed: (.*)$", msg)
    if m:
        e = m.group(1).lower()
        why = ("connection refused" if "refused" in e else "timed out" if "timed out" in e
               else "bad base URL" if "url" in e else "no HTTP answer")
        return "fail", f"the request failed: {why}", None, None
    return "fail", "failed (detail withheld: the runner's message would quote the test)", None, None


def contracts_py(args):
    if "--contracts" in args[:-1]:
        return args[args.index("--contracts") + 1]
    if os.path.exists(".rebuild-plugin"):
        # The marker opens with `#` comment lines (rebuild_init.py writes them); the path is the first other line.
        root = next((l.strip() for l in read_text(".rebuild-plugin").splitlines() if l.strip() and not l.startswith("#")), "")
        p = os.path.join(root, "contracts", "v1", "contracts.py")
        if root and os.path.exists(p):
            return p
    return None


def _run(cmd, timeout, **kw):
    """subprocess.run, with a hung build or a missing program turned into a `not run` reason (design rule 6)
    instead of a traceback that leaves no report."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, **kw), None
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout} s"
    except OSError as e:
        return None, f"could not start {cmd[0]} ({e.strerror or e})"


PLAYWRIGHT_CONFIG = """module.exports = {{ testDir: {test_dir}, outputDir: {out}, reporter: 'line',
  use: {{ baseURL: process.env.ACCEPT_BASE_URL }} }};
"""


def run_one(entry, hold, args):
    """(result, observed, pointer, value) for one hidden test."""
    path = bundle_path(hold, entry.get("path"))
    runner = entry.get("runner")
    if not path or not os.path.exists(path):
        return "not run", "the hidden test file is not in the holdout repo", None, None
    if entry.get("sha256") and sha256_file(path) != entry["sha256"]:
        return "not run", "the hidden test changed since gate-4 locked the manifest", None, None
    withheld = "the runner's output is withheld because it quotes the test"
    if runner == "http":
        cpy = contracts_py(args)
        if not cpy:
            return "not run", "contracts.py not found (pass --contracts, or check .rebuild-plugin)", None, None
        r, why = _run([sys.executable, cpy, "run-http", path], 600)
        if why:
            return "not run", why, None, None
        if r.returncode == 0:
            return "pass", "", None, None
        # quoteattr picks single quotes when the message holds a double quote (a JSON value always does).
        m = re.search(r"<failure message=([\"'])(.*?)\1", r.stdout, re.S)
        return observed(html.unescape(m.group(2)) if m else "")
    if runner == "playwright":
        repo = args[args.index("--repo") + 1] if "--repo" in args[:-1] else None
        cli = os.path.join(repo, "node_modules", "@playwright", "test", "cli.js") if repo else None
        if not cli or not os.path.exists(cli) or not shutil.which("node"):
            return "not run", "no @playwright/test in the code repo's node_modules (pass --repo <code repo>), or no node", None, None
        # The code repo supplies only the runner. Its own playwright.config is lane-written code and would put
        # traces, snippets and expected values into test-results/ inside the repo, where a lane reads them, so
        # the run uses a config written outside every repo, with its output there too, and deletes it.
        import tempfile
        tmp = tempfile.mkdtemp(prefix="holdout-pw-")
        try:
            cfg = os.path.join(tmp, "playwright.config.js")
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write(PLAYWRIGHT_CONFIG.format(test_dir=json.dumps(os.path.dirname(os.path.abspath(path))),
                                                  out=json.dumps(os.path.join(tmp, "out"))))
            env = {**os.environ, "NODE_PATH": os.path.join(os.path.abspath(repo), "node_modules")}
            r, why = _run(["node", cli, "test", "--config", cfg, os.path.basename(path)], 1800, cwd=tmp, env=env)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if why:
            return "not run", why, None, None
        return ("pass", "", None, None) if r.returncode == 0 else ("fail", f"failed (exit {r.returncode}); {withheld}", None, None)
    if runner == "maestro":
        if not shutil.which("maestro"):
            return "not run", "maestro is not installed", None, None
        r, why = _run(["maestro", "test", path], 1800)
        if why:
            return "not run", why, None, None
        return ("pass", "", None, None) if r.returncode == 0 else ("fail", f"failed (exit {r.returncode}); {withheld}", None, None)
    return "not run", f"{runner} tests have no settled format in contracts v1", None, None


def cmd_run(args):
    sid = next((a for a in args if re.fullmatch(r"S\d+", a)), None)
    if not sid:
        return die("usage: holdout.py run <Sn> [--repo <code repo>] [--contracts <contracts.py>]")
    if not os.path.exists(RECORD):
        return die(f"{RECORD} is missing: no split has run.")
    if not os.path.exists(MANIFEST):
        return die(f"{MANIFEST} is missing: the split record exists but the manifest it hashed does not.")
    try:
        rec = load_json(RECORD)
        tests = load_json(MANIFEST).get("tests") or []
    except (OSError, ValueError, AttributeError) as e:
        return die(f"{RECORD} or {MANIFEST} cannot be read: {e}")
    by_crit = {}
    for t in tests:
        by_crit.setdefault(t.get("criterion"), []).append(t)
    hold = holdout_dir()
    if not hold:
        return die(f"the local config ({os.path.join(rebuild_data_dir(), HOLDOUT_CONFIG)}) names no holdout folder "
                   f"for this workbench; the hidden tests cannot be found. Run it as the user who split them.")
    results = []
    try:
        import departures  # vendored sibling; a workbench without it explains nothing rather than failing the run
    except ImportError:
        departures = None
    rank = {"not run": 0, "fail": 1, "explained": 2, "pass": 3}
    for c in (rec.get("slices") or {}).get(sid, []):
        worst = None
        for entry in by_crit.get(c) or [None]:
            result, obs, ptr, value = run_one(entry, hold, args) if entry else (
                "not run", "not in the workbench manifest", None, None)
            did = departures.explained_by(c, entry.get("runner"), ptr, value) if departures and result == "fail" else None
            if did:  # 05 P6 step 2: a failure a decided departure's match rule covers is explained
                result, obs = "explained", f"explained by {did}: {obs}"
            if worst is None or rank[result] < rank[worst[0]]:
                worst = (result, obs, (entry or {}).get("runner"))
        results.append({"criterion": c, "runner": worst[2], "result": worst[0], "observed": worst[1]})
    out_dir = os.path.join("parity", "holdout")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{sid}.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"slice": sid, "results": results}, indent=2, ensure_ascii=False) + "\n")
    lines = [f"# Hidden suite, {sid}", "", "Per criterion; a failure says what the build did, never what the test wants.",
             "", "| Criterion | Result | Observed |", "|---|---|---|"]
    lines += [f"| {x['criterion']} | {x['result']} | {x['observed'].replace('|', '/')} |" for x in results]
    with open(os.path.join(out_dir, f"{sid}.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    for x in results:
        print(f"{x['criterion']}: {x['result']}{' — ' + x['observed'] if x['observed'] else ''}")
    passed = sum(1 for x in results if x["result"] in ("pass", "explained"))
    print(f"{sid}: {passed} of {len(results)} hidden tests pass or are explained by a departure. Report: {out_dir}/{sid}.md")
    return 0 if passed == len(results) else 1


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        return die("no locks/pipeline.yaml here — run from the workbench root.")
    if args and args[0] == "split":
        return cmd_split(args[1:])
    if args and args[0] == "run":
        return cmd_run(args[1:])
    if args and args[0] == "reconcile":
        return cmd_reconcile()
    return die("usage: holdout.py split [--seed <n>] | reconcile | run <Sn> [--repo <code repo>] [--contracts <contracts.py>]")


if __name__ == "__main__":
    sys.exit(main())
