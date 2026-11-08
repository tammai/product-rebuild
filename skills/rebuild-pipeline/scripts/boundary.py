#!/usr/bin/env python3
"""boundary.py — a slice boundary's G6, cheapest check first (spec 05 P6). Run from the workbench root.

  python3 scripts/boundary.py <Sn>                 # run G6 for the slice, with ACCEPT_BASE_URL at its build
  python3 scripts/boundary.py sample <Sn> [--seed <n>]   # draw the human sample (step 6)
  python3 scripts/boundary.py hunted <Sn>          # record that bug-hunter ran for the slice (step 5)
  python3 scripts/boundary.py remine-done          # record that the upstream re-mine ran today

WHY IT EXISTS. G6 is where a slice is judged against the reference instead of against its own tests, and its
steps differ by orders of magnitude in cost: re-running a recorded test is seconds, a bug-hunter run is a
budget. So each step runs only when the ones before it left no build-defect or spec-gap open (P6), and what
they find is batched into one fix round per class by route.py. What stays with the orchestrator and the user is
every decision: running bug-hunter (a skill, which a script cannot start), routing, departures, and the human
sample.

THE STEPS, in P6's order:
  0. Archive each lane's record (lane_plan.py archive), so the slice review reads them in their final state.
  1. Open suite: the slice's open recorded tests against ACCEPT_BASE_URL; each failure is re-run once (flaky
     rules unchanged: a pass on the re-run is flaky, not a finding). What still fails, and no decided departure
     names, becomes a reproduced build-defect finding in parity/findings/<Sn>/.
  2. Hidden suite: holdout.py run. A failure becomes a finding in the holdout repo, out of every lane's reach.
  3. Equivalence: equiv.py replay --all when the lane applies (posture observe or own-code, reference runs).
  4. Coverage and regression: parity.py and slice_review.py, unchanged in purpose.
  5. bug-hunter: prints the command; `hunted` records that it ran.
  6. Human sample: `sample` draws 2–3 features into plan/slice-reviews/<Sn>.md for a person to compare.

THE BOUNDARY PASSES when the open and hidden suites are green or explained, no high finding is open, bug-hunter
has run, and the human sample is recorded. EXIT CODES: 0 pass; 2 not yet (the output says why and what next).
"""
import json
import os
import random
import re
import subprocess
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
REMINE_FILE = os.path.join("parity", "last-remine")
REMINE_DAYS = 30
# rspec owns discovery (05 D3) but has no refresh: its coverage pass builds the reference list (docs navigation
# and the last 12 months of changelog) once and reuses docs/audit/reference.md. So the re-mine is this repo's
# reminder and rspec's work (coordinator pr-6 Q3); docs/MIGRATION-3.md places it.
REMINE_HOW = ("delete docs/audit/reference.md, rerun rspec:features' coverage pass, triage what it adds with "
              "rspec:features triage, then: python3 scripts/boundary.py remine-done")
SAMPLE_SIZE = 3  # P6: 2–3 features; all of them when the slice has fewer
CLASSES = "build-defect|spec-gap|reference-defect|accepted-departure|test-defect|flaky|environment"


def _run(script, *args, env=None):
    return subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def _read(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


def _write(p, text):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _state(sid):
    p = os.path.join("plan", "boundaries", f"{sid}.json")
    return json.loads(_read(p)) if os.path.exists(p) else {}


def _save_state(sid, st):
    _write(os.path.join("plan", "boundaries", f"{sid}.json"), json.dumps(st, indent=2) + "\n")


def _remine_status():
    """(text, due) for the 30-day upstream re-mine. Printed for information only: it is not one of P6's boundary
    conditions, so it never holds a boundary."""
    src = _read("sources.yaml") if os.path.exists("sources.yaml") else ""
    block = re.search(r"^reference:\n((?:[ \t]+.*\n|\n)*)", src, re.M)
    if block and re.search(r"^[ \t]+upstream:[ \t]*[\"']?frozen[\"']?[ \t]*(?:#.*)?$", block.group(1), re.M):
        return "Upstream re-mine: reference is frozen, no re-mine.", False
    if not os.path.exists(REMINE_FILE):
        return f"Upstream re-mine: DUE. None is recorded. To re-mine: {REMINE_HOW}", True
    raw = _read(REMINE_FILE).strip()
    try:
        last = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return f"Upstream re-mine: DUE. {REMINE_FILE} holds {raw!r}, not a date. To re-mine: {REMINE_HOW}", True
    age = (date.today() - last).days
    if age >= REMINE_DAYS:
        return (f"Upstream re-mine: DUE. Last on {raw}, {age} days ago (interval {REMINE_DAYS}). To re-mine: "
                f"{REMINE_HOW}"), True
    return f"Upstream re-mine: not due. Last on {raw}, {age} days ago (interval {REMINE_DAYS}).", False


def _remine_done():
    os.makedirs("parity", exist_ok=True)
    today = date.today().isoformat()
    _write(REMINE_FILE, today + "\n")
    print(f"Recorded the upstream re-mine as of {today} in {REMINE_FILE}. Commit it with the parity report.")
    return 0


# ---------------------------------------------------------------- findings

def _lock_rows():
    import holdout
    return {c["id"]: c for c in (holdout.load_json(os.path.join("docs", "criteria.lock.json")).get("criteria") or [])}


def _next_id(folder, prefix):
    nums = [int(m.group(1)) for f in (os.listdir(folder) if os.path.isdir(folder) else [])
            for m in [re.match(rf"^{prefix}-(\d+)\.json$", f)] if m]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):04d}"


def _write_finding(folder, source, criterion, observed, test_path, contracts, closed=(), runner="http"):
    """A reproduced build-defect finding for a recorded test that failed twice; reuses an open one for the same
    criterion and source, so a boundary run twice does not double-count. A closed one is never reused: a
    criterion that fails again after its fix round is a regression, and reusing the closed id left it routed
    nowhere while the boundary said NOT YET forever."""
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        try:
            old = json.loads(_read(os.path.join(folder, f)))
        except ValueError:
            continue
        if old.get("source") == source and old.get("criterion") == criterion and old.get("id") not in closed:
            return old["id"], False
    row = _lock_rows().get(criterion) or {}
    fid = _next_id(folder, "BND")  # contracts C6 ids are letters, a dash, digits: no "G6"
    repro = {"runner": runner, "manual": f"run the recorded {runner} test for {criterion} against the slice build"}
    if runner == "http":
        try:
            repro = {"runner": "http", "steps": contracts.parse_yaml(_read(test_path)).get("steps") or []}
        except Exception:
            repro = {"runner": "http", "steps": []}
    f = {"id": fid, "source": source, "class": "build-defect", "severity": "high" if row.get("priority") == "MVP" else "medium",
         "criterion": criterion, "rule": None, "feature": row.get("feature"),
         "repro": repro,
         "observed": {"rebuild": observed, "reference": "green when recorded against the reference (level 2)"},
         "route": "sdlc", "verified_by": {"agent": "boundary.py re-run", "result": "reproduced"}}
    _write(os.path.join(folder, f"{fid}.json"), json.dumps(f, indent=2, ensure_ascii=False) + "\n")
    return fid, True


class NotRun(Exception):
    """The open findings could not be counted. Every caller refuses on it: zero open findings is a claim, and
    when contracts.py was missing it used to read as "none open" and let Gate 5 lock over a high finding."""


def _open_findings(sid):
    """Routed findings of the slice that are not closed or dropped, the human sample's `differs` lines written
    as findings first. A finding that is not finding-v1 counts as open (class `invalid`, severity high): it
    cannot be routed, so nothing has shown it is harmless. Raises NotRun when they cannot be counted."""
    import route
    contracts = route.plugin_contracts()
    if not contracts:
        raise NotRun("the plugin's contracts/v1/contracts.py was not found through .rebuild-plugin")
    try:
        route.sync_sample(sid, contracts)
        closed = set(route.load_state(sid)["closed"])
        found = route.findings(sid)
    except (OSError, ValueError, KeyError) as e:
        raise NotRun(f"plan/fix-rounds/{sid}.json or a finding cannot be read ({e})")
    out = []
    for p, f, _h in found:
        if isinstance(f, dict) and f.get("id") in closed:
            continue
        if not isinstance(f, dict) or any(s == "error" for s, _m in contracts.check_finding(f)):
            fid = f.get("id") if isinstance(f, dict) and isinstance(f.get("id"), str) else os.path.basename(p)
            out.append({"id": fid, "class": "invalid", "severity": "high"})
            continue
        r = contracts.finding_route(f)
        if r is None or r == "drop" or route.departure_for(f):
            continue
        out.append(f)
    return out


def _blocking(sid):
    return [f for f in _open_findings(sid) if f["class"] in ("build-defect", "spec-gap", "invalid")]


# ---------------------------------------------------------------- steps

def _code_repos(args):
    """The code repos G6 reads: `--repo <path>` (repeatable), else every repo repos.yaml lists."""
    import holdout
    given = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--repo"]
    return [os.path.abspath(p) for p in given] or holdout.listed_repos()


def _junit_states():
    """{criterion: (state, where)} from the joint run's newest AC JUnit in the workbench's parity/, the failures'
    re-run file laid over it (P6 step 1: the open suite of a non-http runner is already run at the joint run,
    so G6 reads its JUnit instead of running a harness it does not own). The orchestrator starts that run from
    the workbench root (lanes may not write the workbench), and parity.py and slice_review.py read the same
    files, so all three agree on one run. A case counts for a criterion whose ID its name holds; the re-run
    decides a case it repeats, and a failure the re-run passes is flaky."""
    import acsuite
    out = {}
    files = acsuite.ac_junit_files(".")
    if not files:
        return out
    newest = files[0]
    joint = acsuite.read_ac_suite(newest["path"]) or {}
    rerun = acsuite.read_ac_suite(acsuite.ac_rerun_path(newest["date"], ".")) or {}
    again = {c["name"]: c["state"] for c in rerun.get("cases") or []}
    for c in joint.get("cases") or []:
        for cid in re.findall(r"F-[A-Z][A-Z0-9]*-\d+\.AC\d+", c["name"]):
            state = c["state"]
            if state == "failed" and again.get(c["name"]) == "passed":
                state = "flaky"
            elif state == "failed" and c["name"] not in again:
                state = "failed, not re-run"
            if out.get(cid, ("passed",))[0] == "passed":
                out[cid] = (state, newest["path"])
    return out


def _open_suite(sid, contracts, cpy, closed):
    """(green, lines): the slice's open recorded tests. HTTP ones run here, each failure re-run once; the other
    runners' results come from the joint run's JUnit in the workbench."""
    import holdout
    import route
    missing = [p for p in (os.path.join("docs", "criteria.lock.json"), holdout.MANIFEST) if not os.path.exists(p)]
    if missing:
        return False, [f"  not run: no {' or '.join(missing)} (rspec's check writes them before Gate 4)"]
    feats = set(holdout.slices().get(sid) or [])
    rows = _lock_rows()
    tests = [t for t in (holdout.load_json(holdout.MANIFEST).get("tests") or [])
             if t.get("visibility", "open") == "open" and (rows.get(t["criterion"]) or {}).get("feature") in feats]
    if not tests:
        return True, ["  no open recorded tests in this slice"]
    green, lines = True, []
    junit = _junit_states() if any(t.get("runner") != "http" for t in tests) else {}
    folder = os.path.join("parity", "findings", sid)
    for t in tests:
        cid, runner = t["criterion"], t.get("runner")
        path = holdout.bundle_path(holdout.BUNDLE, t.get("path"))
        if not path:
            green = False
            lines.append(f"  {cid}: not run: its manifest path leaves {holdout.BUNDLE}")
            continue
        if runner != "http":
            state, where = junit.get(cid, (None, None))
            if state == "passed":
                continue
            if state == "flaky":
                lines.append(f"  {cid}: failed in the lanes' run, passed on its re-run: flaky, not a finding")
                continue
            green = False
            if state is None:
                lines.append(f"  {cid}: not run: no joint-run JUnit in the workbench's parity/ holds a {runner} case "
                             f"naming it (the orchestrator's joint run writes parity/<date>-ac.xml)")
            elif state == "failed":
                fid, new = _write_finding(folder, "g6-open", cid, f"its {runner} test failed twice in the lanes' runs "
                                          f"({where})", path, contracts, closed, runner)
                lines.append(f"  {cid}: fails in the lanes' run and its re-run -> {'new' if new else 'open'} finding {fid}")
            else:
                lines.append(f"  {cid}: {state} in {where}: re-run the failed specs (the orchestrator: lanes_check.py stamp --rerun)")
            continue
        if not os.environ.get("ACCEPT_BASE_URL"):
            green = False
            lines.append(f"  {cid}: not run: ACCEPT_BASE_URL is not set (point it at the slice build)")
            continue
        if not cpy:
            green = False
            lines.append(f"  {cid}: not run: contracts.py not found through .rebuild-plugin")
            continue
        ok, msg = _http(cpy, path)
        if ok is None:
            green = False
            lines.append(f"  {cid}: not run: {msg}")
            continue
        if ok:
            continue
        ok2, msg2 = _http(cpy, path)
        if ok2:
            lines.append(f"  {cid}: failed, then passed on its one re-run: flaky, not a finding")
            continue
        if ok2 is None:
            green = False
            lines.append(f"  {cid}: not run on the re-run: {msg2}")
            continue
        result, obs, ptr, value = holdout.observed(msg2)
        did = route.departure_for({"criterion": cid}, "http", ptr, value)
        if did:
            lines.append(f"  {cid}: fails twice, explained by {did}")
            continue
        green = False
        fid, new = _write_finding(folder, "g6-open", cid, msg2, path, contracts, closed)
        lines.append(f"  {cid}: fails twice ({msg2}) -> {'new' if new else 'open'} finding {fid}")
    return green, lines


def _http(cpy, path):
    """(passed, message); passed None when the run could not happen (a hang, or python missing)."""
    try:
        r = subprocess.run([sys.executable, cpy, "run-http", path], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        return None, "timed out after 600 s"
    except OSError as e:
        return None, f"could not start contracts.py ({e})"
    if r.returncode == 0:
        return True, ""
    import html
    m = re.search(r"<failure message=([\"'])(.*?)\1", r.stdout, re.S)
    return False, html.unescape(m.group(2)) if m else f"exit {r.returncode}"


def _hidden_suite(sid, contracts, repos, closed):
    import holdout
    if not os.path.exists(holdout.RECORD):
        return False, ["  not run: no holdout split (plan/holdout.json)"]
    pw = [r for r in repos if os.path.exists(os.path.join(r, "node_modules", "@playwright", "test", "cli.js"))]
    r = _run("holdout.py", "run", sid, *(["--repo", (pw or repos)[0]] if repos else []))
    p = os.path.join("parity", "holdout", f"{sid}.json")
    if not os.path.exists(p):
        return False, [f"  not run: holdout.py wrote no report ({(r.stdout + r.stderr).strip()[-300:]})"]
    entries = {}
    for t in holdout.load_json(holdout.MANIFEST).get("tests") or []:
        entries.setdefault(t.get("criterion"), t)
    green, lines = True, []
    for x in json.loads(_read(p)).get("results") or []:
        if x["result"] in ("pass", "explained"):
            lines.append(f"  {x['criterion']}: {x['result']}")
            continue
        green = False
        if x["result"] == "fail":
            entry = entries.get(x["criterion"]) or {}
            folder = os.path.join(holdout.holdout_dir(), "findings", sid)
            test = holdout.bundle_path(holdout.holdout_dir(), entry.get("path")) or ""
            fid, new = _write_finding(folder, "g6-hidden", x["criterion"], x["observed"], test, contracts, closed,
                                      x.get("runner") or "http")
            lines.append(f"  {x['criterion']}: fail ({x['observed']}) -> {'new' if new else 'open'} finding {fid} (kept in the holdout repo)")
        else:
            lines.append(f"  {x['criterion']}: not run: {x['observed']}")
    return green, lines


def _budget(key):
    p = "rebuild.yaml"
    block = re.search(r"^budgets:[ \t]*\n((?:(?:[ \t]+.*)?\n)*)", _read(p) + "\n", re.M) if os.path.exists(p) else None
    m = block and re.search(rf"^[ \t]+{key}:[ \t]*(\S+)", block.group(1), re.M)
    return m.group(1) if m else None


def _cost(sid, contracts):
    """The slice's cost by stage from logs/<Sn>/*.jsonl (contracts C7), or why not."""
    import glob
    files = sorted(glob.glob(os.path.join("logs", sid, "*.jsonl")))
    if not files:
        return f"  cost: not run: no cost log in logs/{sid}/ (cost.py add, and bug-hunter's --cost-log)"
    if not contracts:
        return "  cost: not run: contracts.py not found through .rebuild-plugin"
    text = "".join(_read(f) for f in files)
    bad = [m for s, m in contracts.check_cost(text) if s == "error"]
    if bad:
        return f"  cost: not run: the log is not C7 ({bad[0]})"
    lines = []
    for stage, t in sorted(contracts.sum_cost(text).items()):
        lines.append(f"  {stage}: {t['runs']} run{'s' if t['runs'] != 1 else ''}, {round(t['wall_s'])} s, {t['turns']} turns, "
                     f"{t['tokens_in']} in / {t['tokens_out']} out tokens"
                     f"{', ' + str(t['tokens_unreported']) + ' unreported' if t['tokens_unreported'] else ''}")
    return "\n".join(lines)


def _sample_state(sid):
    """(recorded?, why not), read by route.sample_entries, the one parser of the section."""
    import route
    sample = route.sample_entries(sid)
    if sample is None:
        return False, f"not drawn: python3 scripts/boundary.py sample {sid}"
    reviewer, entries = sample
    if not reviewer:
        return False, f"no reviewer named in plan/slice-reviews/{sid}.md"
    bad = [e["feature"] for e in entries if e["verdict"] not in ("agree", "differs")]
    if not entries or bad:
        return False, (f"not recorded for {', '.join(bad) or 'any feature'} (agree, or differs: <what> "
                       f"(class: {CLASSES}[, severity: high|medium|low]))")
    return True, ""


def _boundary(sid, args=()):
    import holdout
    import route
    contracts = route.plugin_contracts()
    cpy = holdout.contracts_py([])
    st = _state(sid)
    repos = _code_repos(list(args))
    bad = holdout.exposure(holdout.holdout_dir())
    if bad:
        print(f"Boundary {sid}: REFUSED. The holdout repo is reachable from a code repo: {'; '.join(bad)}. "
              f"Remove it from that repo before G6 runs.")
        return 2
    changed, err = holdout.reconcile()
    if err:
        print(f"Boundary {sid}: REFUSED. {err}")
        return 2
    if changed:
        print(f"Boundary {sid}: the hidden entries a re-verify dropped are back in {holdout.MANIFEST}; commit it and "
              f"{holdout.RECORD}.")
    try:
        closed = set(route.load_state(sid)["closed"])
    except (OSError, ValueError) as e:
        print(f"Boundary {sid}: not run: plan/fix-rounds/{sid}.json cannot be read ({e}).")
        return 2

    rec_path = os.path.join("plan", "lane-plans", f"{sid}.yaml")
    lanes = []
    if os.path.exists(rec_path):
        try:
            lanes = sorted(((json.loads(re.sub(r"^#.*\n", "", _read(rec_path), flags=re.M)) or {}).get("lanes") or {}).keys())
        except ValueError:
            print(f"== 0. lane records: {rec_path} is not readable JSON; archive each lane with lane_plan.py by hand.")
    print(f"== 0. {sid}: archive lane records ({len(lanes)} recorded)")
    for lane in lanes:
        r = _run("lane_plan.py", "archive", sid, lane)
        text = (r.stdout + r.stderr).strip()
        if r.returncode and "already archived" in text:
            print(f"  {lane}: already archived")
        elif r.returncode:
            print(f"  {lane}: NOT archived. {text}")
        else:
            print(f"  {lane}: {text}")

    def stop(after):
        try:
            b = _blocking(sid)
        except NotRun as e:
            print(f"\nStopped after {after}: open findings not counted: not run: {e}.")
            return True
        if b:
            print(f"\nStopped after {after}: {len(b)} open build-defect/spec-gap finding(s) "
                  f"({', '.join(f['id'] for f in b)}). Route them: python3 scripts/route.py {sid}. "
                  f"Run the boundary again once the fix round closes them.")
            return True
        return False

    print("\n== 1. open suite (each failure re-run once)")
    open_green, lines = _open_suite(sid, contracts, cpy, closed)
    print("\n".join(lines) or "  all green")
    if stop("the open suite"):
        return 2
    print("\n== 2. hidden suite")
    hidden_green, lines = _hidden_suite(sid, contracts, repos, closed)
    print("\n".join(lines) or "  none hidden in this slice")
    if stop("the hidden suite"):
        return 2
    print("\n== 3. equivalence")
    r = _run("equiv.py", "status")
    if "DOES NOT APPLY" in r.stdout:
        print("  does not apply here (equiv.py status says why)")
    else:
        r = _run("equiv.py", "replay", "--all")
        print("  " + ((r.stdout + r.stderr).strip()[-1500:] or "(no output)").replace("\n", "\n  "))
    for label, script, args in (("4. coverage: parity", "parity.py", []), ("4. regression: slice review", "slice_review.py", [sid])):
        r = _run(script, *args)
        print(f"\n== {label}")
        out = (r.stdout + r.stderr).strip()
        if r.returncode:
            # Design rule 6: a report that could not run is never relayed as if it were step 4's result.
            last = out.splitlines()[-1] if out else f"exit {r.returncode}, no output"
            print(f"  not run: {last if not last.startswith('not run: ') else last[len('not run: '):]}")
            continue
        print("  " + (out[-1500:] or "(no output)").replace("\n", "\n  "))
    print(f"\n== {_remine_status()[0]} (information; not a boundary condition)")
    print("\n== 5. bug-hunter")
    if st.get("hunted"):
        print(f"  ran (recorded {st['hunted']}); its findings are in parity/findings/{sid}/")
    else:
        budget = _budget("bughunter_tokens_per_slice") or "<slice budget>"
        hunters = _budget("hunters_per_slice")
        print(f"  not run yet. Run it (Playwright in the code repo: add browser mode), then record it:\n"
              f"    /bug-hunter:hunt --oracle docs/ --target <the slice build> --reference <the reference> "
              f"--format finding-v1 --out parity/findings/{sid}/ --yes --budget {budget}{' --max ' + hunters if hunters else ''} "
              f"--cost-log logs/{sid}/cost.jsonl\n"
              f"    python3 scripts/boundary.py hunted {sid}")
    if stop("bug-hunter"):
        return 2
    print("\n== 6. human sample")
    sampled, why = _sample_state(sid)
    print("  recorded" if sampled else f"  {why}")

    print("\n== cost (05 P9)")
    print(_cost(sid, contracts))
    try:
        high = [f["id"] for f in _open_findings(sid) if f.get("severity") == "high"]
    except NotRun as e:
        high = [f"not counted: {e}"]
    missing = [m for m, ok in (("the open suite is not green", open_green), ("the hidden suite is not green", hidden_green),
                               (f"high findings are open ({', '.join(high)})", not high),
                               ("bug-hunter has not run", bool(st.get("hunted"))),
                               ("the human sample is not recorded", sampled)) if not ok]
    if missing:
        print(f"\nBoundary {sid}: NOT YET — " + "; ".join(missing) + ".")
        return 2
    print(f"\nBoundary {sid}: PASS — open and hidden suites green or explained, no open high finding, bug-hunter run, "
          f"human sample recorded.")
    return 0


def _sample(args):
    import holdout
    sid = args[0] if args else None
    if not sid or not re.fullmatch(r"S\d+", sid):
        print("Usage: boundary.py sample <Sn> [--seed <n>]", file=sys.stderr)
        return 1
    p = os.path.join("plan", "slice-reviews", f"{sid}.md")
    if os.path.exists(p) and re.search(r"^## Human sample\b", _read(p), re.M):
        print(f"{p} already has a human sample: it is drawn once per slice.", file=sys.stderr)
        return 1
    feats = holdout.slices().get(sid) or []
    if not feats:
        print(f"{sid} has no features in docs/build-plan.md.", file=sys.stderr)
        return 1
    rows = _lock_rows().values()
    weight = {f: 1 + sum(1 for c in rows if c.get("feature") == f and c.get("priority") != "Drop" and (c.get("level") or 0) < 2)
              for f in feats}
    seed = int(args[args.index("--seed") + 1]) if "--seed" in args[:-1] else random.SystemRandom().randrange(2 ** 31)
    rng = random.Random(seed)
    pool, picked = list(feats), []
    while pool and len(picked) < SAMPLE_SIZE:
        x = rng.uniform(0, sum(weight[f] for f in pool))
        for f in pool:
            x -= weight[f]
            if x <= 0:
                break
        picked.append(f)
        pool.remove(f)
    section = (f"## Human sample\n\nSeed: {seed} · Reviewer: <your name>\n\n"
               f"Compare each feature below with the running reference, as a user would, and write `agree`, or "
               f"`differs: <what> (class: {CLASSES})`. Each `differs` becomes a finding (route.py). Autopilot never "
               f"fills this in; the boundary stays open until a person does.\n\n" + "".join(f"- {f}:\n" for f in picked))
    body = _read(p).rstrip("\n") + "\n\n" if os.path.exists(p) else f"# Slice review, {sid}\n\n"
    _write(p, body + section)
    print(f"{sid}: human sample of {', '.join(picked)} (seed {seed}) in {p}")
    return 0


def _hunted(args):
    sid = args[0] if args else None
    if not sid or not re.fullmatch(r"S\d+", sid):
        print("Usage: boundary.py hunted <Sn>", file=sys.stderr)
        return 1
    st = _state(sid)
    st["hunted"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _save_state(sid, st)
    print(f"{sid}: bug-hunter recorded as run ({st['hunted']}).")
    return 0


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = sys.argv[1:] if argv is None else list(argv)
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    if args and args[0] == "remine-done":
        return _remine_done()
    if args and args[0] == "sample":
        return _sample(args[1:])
    if args and args[0] == "hunted":
        return _hunted(args[1:])
    if args and re.fullmatch(r"S\d+", args[0]):
        return _boundary(args[0], args[1:])
    print("Usage: boundary.py <Sn> | sample <Sn> [--seed <n>] | hunted <Sn> | remine-done", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
