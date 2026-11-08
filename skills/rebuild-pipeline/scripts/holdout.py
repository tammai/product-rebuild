#!/usr/bin/env python3
"""holdout.py — hidden tests (spec 05 P4, decision D4). Run from the workbench root.

  python3 scripts/holdout.py split [--seed <n>]                 # after rspec:check, before gate.py lock gate-4
  python3 scripts/holdout.py run <Sn> [--repo <code repo>] [--contracts <contracts.py>]
                                                                 # at G6, with ACCEPT_BASE_URL set to the slice build

WHY HIDDEN TESTS. Every test a builder can see is one it can build to: a lane whose suite passes has
shown the build agrees with the tests it read, not that it does what the reference does. A share of
the recorded tests the lanes never see measures the second thing. D4: 25% of each slice's level 2
tests (recorded against the reference, contracts C3), at least one per feature with three or more
criteria, chosen from a seed recorded at the Gate 4 lock so anyone can re-derive the list.

SPLIT moves the chosen files out of `docs/acceptance/` into a sibling git repo, `<project>-holdout/`,
which is never a submodule of any code repo (the split refuses when a repo listed in repos.yaml
contains or references it), marks them `visibility: hidden` in the workbench manifest (contracts C4
leaves this to product-rebuild), and writes `plan/holdout.json`. It runs before the gate-4 lock, not
after: the lock hashes the manifest and records the seed and list hash, and gate.py refuses gate-4
until that record matches the manifest. Level 2 already excludes flaky tests (rspec's verify keeps a
criterion with a pass and a failure at level 1), so flaky ones are never hidden (06, Risks).

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


def holdout_dir():
    """<workbench>/../<project>-holdout, the path the reference guard also denies to lanes."""
    project = None
    p = os.path.join("locks", "pipeline.yaml")
    if os.path.exists(p):
        m = re.search(r"^project:[ \t]*(\S+)", read_text(p), re.M)
        project = m.group(1).strip("\"'") if m else None
    project = project or re.sub(r"-workbench\Z", "", os.path.basename(os.getcwd()))
    return os.path.join(os.path.dirname(os.getcwd()), f"{project}-holdout")


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
        cands = sorted(t["criterion"] for t in tests
                       if t.get("visibility", "open") == "open" and level.get(t["criterion"]) == 2
                       and feature_of.get(t["criterion"]) in feats)
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
    hold = holdout_dir()
    bad = exposure(hold)
    if bad:
        return die(f"the holdout repo {hold} would be reachable from a code repo: {'; '.join(bad)}. "
                   f"Hidden tests must never be in, or a submodule of, any code repo.")
    seed = int(args[args.index("--seed") + 1]) if "--seed" in args[:-1] else random.SystemRandom().randrange(2 ** 31)
    manifest = load_json(MANIFEST)
    tests = manifest.get("tests") or []
    chosen = choose(seed, slice_map, load_json(os.path.join(SPEC, "criteria.lock.json")), tests)
    hidden = sorted(c for ids in chosen.values() for c in ids)
    entries = {t["criterion"]: t for t in tests}
    for c in hidden:
        src = os.path.join(BUNDLE, entries[c]["path"])
        if not os.path.exists(src):
            return die(f"{src} (the test for {c}) is missing.")
    os.makedirs(hold, exist_ok=True)
    if not os.path.exists(os.path.join(hold, ".git")):
        git(hold, "init", "-q")
    for c in hidden:
        dst = os.path.join(hold, entries[c]["path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(os.path.join(BUNDLE, entries[c]["path"]), dst)
        entries[c]["visibility"] = "hidden"
    if os.path.isdir(os.path.join(BUNDLE, "seed")):
        shutil.copytree(os.path.join(BUNDLE, "seed"), os.path.join(hold, "seed"), dirs_exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    git(hold, "add", "-A")
    git(hold, "commit", "-qm", f"holdout: {len(hidden)} hidden tests, seed {seed}")
    rec = {"seed": seed, "count": len(hidden), "list_sha256": list_sha256(hidden), "hidden": hidden,
           "slices": chosen, "manifest_sha256": sha256_file(MANIFEST)}
    os.makedirs("plan", exist_ok=True)
    with open(RECORD, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, indent=2) + "\n")
    for sid, ids in chosen.items():
        print(f"{sid}: {len(ids)} hidden")
    print(f"{len(hidden)} hidden tests moved to the holdout repo (committed there, never pushed by this script); "
          f"seed {seed}. Commit the workbench, then lock gate-4.")
    return 0


# ---------------------------------------------------------------- run

def observed(msg):
    """(result, observed) from a run-http failure message, keeping what the build did and dropping what the
    test wanted. Anything this does not recognise is withheld: a message format it has not seen may quote it."""
    if msg.startswith("not run:"):
        return "not run", msg[len("not run:"):].strip()
    if msg.startswith("invalid test:"):
        return "not run", "the hidden test file does not parse"
    for pat, fmt in ((r"status (\d+), expected", "HTTP status {0}"),
                     (r" (/\S*): got (.*), expected ", "{0} was {1}"),
                     (r" (/\S*): not present in the response", "{0} not in the response"),
                     (r" (/\S*): (.*) does not satisfy rule ", "{0} was {1}"),
                     (r"response is not JSON", "the response is not JSON"),
                     (r": request failed: (.*)$", "the request failed: {0}")):
        m = re.search(pat, msg)
        if m:
            return "fail", fmt.format(*m.groups())
    return "fail", "failed (detail withheld: the runner's message would quote the test)"


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


def run_one(entry, hold, args):
    path = os.path.join(hold, entry["path"])
    runner = entry.get("runner")
    if not os.path.exists(path):
        return "not run", "the hidden test file is not in the holdout repo"
    if runner == "http":
        cpy = contracts_py(args)
        if not cpy:
            return "not run", "contracts.py not found (pass --contracts, or check .rebuild-plugin)"
        r = subprocess.run([sys.executable, cpy, "run-http", path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        if r.returncode == 0:
            return "pass", ""
        # quoteattr picks single quotes when the message holds a double quote (a JSON value always does).
        m = re.search(r"<failure message=([\"'])(.*?)\1", r.stdout, re.S)
        return observed(html.unescape(m.group(2)) if m else "")
    if runner == "playwright":
        repo = args[args.index("--repo") + 1] if "--repo" in args[:-1] else None
        cli = os.path.join(repo, "node_modules", "@playwright", "test", "cli.js") if repo else None
        if not cli or not os.path.exists(cli) or not shutil.which("node"):
            return "not run", "no @playwright/test in the code repo's node_modules (pass --repo <code repo>), or no node"
        r = subprocess.run(["node", cli, "test", path], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=1800)
        return ("pass", "") if r.returncode == 0 else (
            "fail", f"failed (exit {r.returncode}); the runner's output is withheld because it quotes the test")
    if runner == "maestro":
        if not shutil.which("maestro"):
            return "not run", "maestro is not installed"
        r = subprocess.run(["maestro", "test", path], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=1800)
        return ("pass", "") if r.returncode == 0 else (
            "fail", f"failed (exit {r.returncode}); the runner's output is withheld because it quotes the test")
    return "not run", f"{runner} tests have no settled format in contracts v1"


def cmd_run(args):
    sid = next((a for a in args if re.fullmatch(r"S\d+", a)), None)
    if not sid:
        return die("usage: holdout.py run <Sn> [--repo <code repo>] [--contracts <contracts.py>]")
    if not os.path.exists(RECORD):
        return die(f"{RECORD} is missing: no split has run.")
    rec = load_json(RECORD)
    entries = {t["criterion"]: t for t in load_json(MANIFEST).get("tests") or []}
    hold = holdout_dir()
    results = []
    for c in (rec.get("slices") or {}).get(sid, []):
        entry = entries.get(c)
        result, obs = run_one(entry, hold, args) if entry else ("not run", "not in the workbench manifest")
        results.append({"criterion": c, "runner": (entry or {}).get("runner"), "result": result, "observed": obs})
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
    passed = sum(1 for x in results if x["result"] == "pass")
    print(f"{sid}: {passed} of {len(results)} hidden tests pass. Report: {out_dir}/{sid}.md")
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
    return die("usage: holdout.py split [--seed <n>] | run <Sn> [--repo <code repo>] [--contracts <contracts.py>]")


if __name__ == "__main__":
    sys.exit(main())
