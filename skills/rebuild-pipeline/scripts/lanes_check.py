#!/usr/bin/env python3
"""lanes_check.py — is a build lane still working, or did its run end and nobody noticed?
Run from the workbench root.

  python3 scripts/lanes_check.py                   # evidence, per repo and worktree
  python3 scripts/lanes_check.py --idle 15         # minutes of silence before "looks stalled"
  python3 scripts/lanes_check.py stamp             # record which code the joint run is about to test
  python3 scripts/lanes_check.py stamp --rerun     # the same, for the rerun of its failures

WHY THIS EXISTS. A lane watched its 45-minute suite with a Monitor, which gives up after at
most 30 minutes, then went idle "waiting for the notification". Nothing woke it: 2½ hours once,
40 minutes once, several 10–20 minute gaps, over two days — and the orchestrator only noticed
when the user asked for status. The orchestrator's 10-minute watchdog (g5-build.md, "Guardrails
you enforce as orchestrator") runs this, so the check is one cheap call and the same in every
project, instead of a hand-assembled `ps | grep` that differs by machine. It is a script and
not a line in a doc because the watchdog has to be the same call on every machine, and a
hand-assembled process listing is not.

EXIT CODES. 0: nothing to act on. 2: a lane looks stalled — a run_phases.py driver died
mid-phase, or no test process or driver is alive and nothing in any repo or run directory has
changed for longer than --idle minutes. It is a heuristic and says so; the orchestrator decides, with the evidence this
prints, and it is that evidence it sends the lane.

RUN DIRECTORIES. A run driven by `run_phases.py` keeps `status.json` (driver pid, current
phase, state) in parity/runs/<local-date>-<label>/. A driver whose pid is alive counts as a run
in progress, even between test processes (a reset or a redeploy runs no test binary). One that
says `running` with a dead pid died mid-phase, and that is reported by name, not inferred from
silence.

WHEN IT EXITS 2 it names the newest file it saw anywhere and its age, so the orchestrator's
nudge can quote evidence: "go.log, written 14 min ago" is something a lane acts on, where
"looks stalled" is something it argues with.

MARKERS. A code repo with no `.rebuild-workbench` marker turns `runbook_guard.py` off silently,
because the guard fails open without it. While a slice is in progress this names the repo and
the one-line fix. pause_check.py carries the same check.

STAMP. JUnit carries no field for the commit it ran against, and that is the one fact needed
to say what a pass on rerun means (acsuite.py count_with_rerun: same commits → flaky, different
→ code changed, unknown → unverified). `stamp` writes parity/<local-date>-ac.meta.json (or
-ac-rerun.meta.json) with every repo's HEAD and whether its tree was dirty. Run it immediately
before the run it describes, from the workbench root, by whichever lane starts that run.

Zero-dependency: repos.yaml is parsed with the same fixed-subset regex as pause_check.py.
"""

import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

import acsuite

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def _read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


# Raw read for JSON the tools wrote themselves (status.json, .last-run.json): no CRLF pass, as
# the Node original had none, and a BOM still makes it unreadable.
def _read_raw(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


# JS String.prototype.trim: not Python's str.strip, which also strips \x1c-\x1f and \x85.
_JS_WS = " \t\n\v\f\r           " \
         "      　﻿"


def _trim(s):
    return s.strip(_JS_WS)


def _js_round(x):
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


# What `${n}` prints for a number: 10, not 10.0; NaN for an unparseable --idle.
def _js_num(x):
    if isinstance(x, float):
        if math.isnan(x):
            return "NaN"
        if math.isinf(x):
            return "Infinity" if x > 0 else "-Infinity"
        if x.is_integer():
            return str(int(x))
    return str(x)


# `Number(x)` for an --idle value: "" is 0, junk is NaN. float() alone accepts "1_0" and "nan".
def _js_number(s):
    s = _trim(s)
    if s == "":
        return 0.0
    if re.fullmatch(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", s):
        return float(s)
    if s in ("Infinity", "+Infinity"):
        return math.inf
    if s == "-Infinity":
        return -math.inf
    return math.nan


# `${x}` for a value read out of a JSON file a person or tool wrote: absent is "undefined", null
# is "null".
def _show(obj, key):
    if not isinstance(obj, dict) or key not in obj:
        return "undefined"
    v = obj[key]
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (dict, list)):
        return "[object Object]" if isinstance(v, dict) else ",".join(map(str, v))
    return str(v)


def _truthy(v):
    return not (v is None or v is False or v == "" or (isinstance(v, (int, float)) and (v == 0 or v != v)))


# The local date-time the report heading carries, in en-US shape ("10/26/2026, 5:03:09 PM") as
# Node's toLocaleString gives under the default locale. Informational only: nothing parses it.
def _local_stamp():
    d = datetime.now()
    h = d.hour % 12 or 12
    return f"{d.month}/{d.day}/{d.year}, {h}:{d.minute:02d}:{d.second:02d} {'PM' if d.hour >= 12 else 'AM'}"


def _iso_now():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


# stderr and stdin are discarded: a directory that is not a repo is an expected answer here
# (null), not a message for the person running the watchdog.
def _git(d, a, raw=False):
    # raw keeps leading whitespace: `git status --porcelain` starts a line with a space for an
    # unstaged change, and trimming the output ate the first line's status columns, so line[3:]
    # cut three characters off that file's name and its mtime was never counted (a bug the Node
    # original had).
    try:
        r = subprocess.run(["git", "-C", d, *a], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", check=True)
        return r.stdout if raw else _trim(r.stdout)
    except (subprocess.CalledProcessError, OSError):
        return None


def _repo_entries():
    out = [{"name": "workbench", "path": os.path.abspath(".")}]
    if not os.path.exists("repos.yaml"):
        return out
    text = _read_text("repos.yaml")
    for m in re.finditer(r"^\s*-\s*(?:name:\s*(\S+)\s*)?path:\s*(\S+)", text, re.M):
        out.append({"name": m.group(1) or m.group(2), "path": os.path.abspath(m.group(2))})
    return out


def _stamp(args):
    rerun = "--rerun" in args
    repos = {}
    problems = []
    for e in _repo_entries():
        name, path = e["name"], e["path"]
        sha = _git(path, ["rev-parse", "HEAD"]) if os.path.exists(path) else None
        if not sha:
            problems.append(f"{name}: no HEAD at {path}")
            continue
        dirty = len(_git(path, ["status", "--porcelain"]) or "") > 0
        repos[name] = {"path": path, "sha": sha, "dirty": dirty}
        if dirty:
            problems.append(f"{name}: uncommitted changes — this run's code cannot be named by a commit")
    out = acsuite.run_meta_path(acsuite.local_date(), {"rerun": rerun})
    os.makedirs("parity", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"started": _iso_now(), "rerun": rerun, "repos": repos}, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {out} — {len(repos)} repo(s) stamped.")
    if problems:
        print("\nA pass on rerun will be reported as UNVERIFIED, because:")
        for p in problems:
            print(f"  - {p}")
        print("Commit first (a WIP commit on the lane's branch is fine), then stamp again.")
    return 0


# Live test processes. Command lines, not image names: on Windows `tasklist` only shows
# `node.exe`, which cannot tell Playwright from the dev server, so PowerShell's Win32_Process
# is asked for the command line instead. ASCII-only classes, as in JS, so `\w` and `\b` mean the
# same on a command line with accented path segments.
_A = re.ASCII
TEST_PROC = [
    re.compile(r'\bgo(\.exe)?"?\s+test\b', _A), re.compile(r'[\\/][\w.-]+\.test(\.exe)?"?(\s|$)', _A),  # go test, and its compiled test binaries
    re.compile(r'playwright(\.cmd)?"?\s+test\b|@playwright[\\/]test', _A), re.compile(r"\bvitest\b", _A), re.compile(r"\bjest\b", _A),
    re.compile(r'\bmaestro(\.bat)?"?\s+test\b', _A), re.compile(r'\bflutter(\.bat)?"?\s+test\b', _A), re.compile(r'\bdart(\.exe)?"?\s+test\b', _A),
    re.compile(r'\bequiv\.py"?\s+(replay|record)\b', _A),
]


def _list_processes():
    try:
        if sys.platform == "win32":
            csv = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine | ConvertTo-Csv -NoTypeInformation"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", check=True).stdout
            out = []
            for l in re.split(r"\r?\n", csv)[1:]:
                m = re.match(r'^"(\d+)","(.*)"$', l)
                if m:
                    out.append({"pid": m.group(1), "command": m.group(2).replace('""', '"')})
            return out
        ps = subprocess.run(["ps", "-axo", "pid=,etime=,command="], stdout=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", check=True).stdout
        out = []
        for l in ps.split("\n"):
            m = re.match(r"^\s*(\d+)\s+(\S+)\s+(.*)$", l)
            if m:
                out.append({"pid": m.group(1), "elapsed": m.group(2), "command": m.group(3)})
        return out
    except (subprocess.CalledProcessError, OSError):
        return None


# Whether a pid is a live process. os.kill(pid, 0) is the POSIX probe, but on Windows Python's
# os.kill TERMINATES the process for any signal other than the two console events, so the probe
# would kill the very driver it was asking about. There it asks the kernel directly. A process
# owned by someone else counts as alive on both (EPERM / ERROR_ACCESS_DENIED): it exists.
def _pid_alive(pid):
    if isinstance(pid, str):
        n = _js_number(pid)
    elif isinstance(pid, (int, float)):
        n = float(pid)
    else:
        return False
    if math.isnan(n) or math.isinf(n) or n != int(n):
        return False
    n = int(n)
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, n)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.GetLastError() == 5  # ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(n, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _scandir_sorted(d):
    # Sorted by name, as libuv's scandir returns them to Node.
    with os.scandir(d) as it:
        return sorted(it, key=lambda e: e.name)


# Playwright writes `.last-run.json` into its outputDir, which is `test-results/` by default and
# whatever playwright.config says otherwise (`e2e/.artifacts/` in one rebuild) — so it is found,
# not assumed: a shallow walk, skipping dependency and build directories.
_SKIP_DIRS = re.compile(r"(node_modules|\.git|\.nuxt|\.output|\.next|dist|build|vendor|workbench)")


def _find_last_run(d, depth=3):
    out = []
    try:
        entries = _scandir_sorted(d)
    except OSError:
        return out
    for e in entries:
        if e.is_file(follow_symlinks=False) and e.name == ".last-run.json":
            out.append(os.path.join(d, e.name))
        elif e.is_dir(follow_symlinks=False) and depth > 0 and not _SKIP_DIRS.fullmatch(e.name):
            out.extend(_find_last_run(os.path.join(d, e.name), depth - 1))
    return out


def _mtime_ms(p):
    return os.stat(p).st_mtime * 1000


# Code repos with no usable `.rebuild-workbench` marker, while a slice is in progress. Copied
# from pause_check.py, not imported, because both are standalone scripts — if you change one,
# change both.
def _slices_in_progress():
    try:
        block = re.search(r"^slices:\n((?:(?:[ \t]+.*)?\n)*)", _read_text(os.path.join("plan", "progress.yaml")), re.M)
        if not block:
            return []
        return [m.group(1) for m in re.finditer(r"^\s+(S[0-9]+):\s*([a-z-]+)", block.group(1), re.M)
                if m.group(2) == "in-progress"]
    except OSError:
        return []


def _check(args):
    def opt(n, d):
        if n in args:
            i = args.index(n)
            if i + 1 < len(args) and args[i + 1]:
                return args[i + 1]
        return d

    procs = _list_processes()
    own_pid = str(os.getpid())
    test_procs = [p for p in (procs or []) if p["pid"] != own_pid and any(rx.search(p["command"]) for rx in TEST_PROC)]

    # Repos and their worktrees: last commit, dirty count, newest change to a dirty file.
    now = time.time() * 1000

    def ago(ms):
        if ms is None:
            return "—"
        m = _js_round((now - ms) / 60000)
        return f"{m} min ago" if m < 60 else f"{m // 60} h {m % 60} min ago"

    rows = []
    last_activity = 0
    # The newest file seen anywhere, by path: what the stall message quotes.
    seen = {"newest": None}

    def see_file(path, mtime):
        if mtime and (seen["newest"] is None or mtime > seen["newest"]["mtime"]):
            seen["newest"] = {"path": path, "mtime": mtime}

    for e in _repo_entries():
        name, path = e["name"], e["path"]
        if not os.path.exists(path):
            rows.append({"label": name, "path": path, "missing": True})
            continue
        trees = []
        wt = _git(path, ["worktree", "list", "--porcelain"])
        if wt:
            trees.extend(m.group(1) for m in re.finditer(r"^worktree (.+)$", wt, re.M))
        if not trees:
            trees.append(path)
        try:
            real = os.path.realpath(path)
        except OSError:
            real = path
        for tree in trees:
            ct = _git(tree, ["log", "-1", "--format=%ct"]) or "0"
            try:
                committed = int(ct) * 1000 or None
            except ValueError:
                committed = None
            status = [l for l in (_git(tree, ["status", "--porcelain"], raw=True) or "").split("\n") if l]
            dirty_mtime = None
            for line in status:
                f = os.path.join(tree, re.sub(r'^"|"$', "", line[3:]).split(" -> ")[-1])
                try:
                    t = _mtime_ms(f)
                    if t > (dirty_mtime or 0):
                        dirty_mtime = t
                    see_file(f, t)
                except OSError:
                    pass  # deleted file
            last_activity = max(last_activity, committed or 0, dirty_mtime or 0)
            branch = _git(tree, ["rev-parse", "--abbrev-ref", "HEAD"]) or "?"
            procs_here = [p for p in test_procs if tree in p["command"]]
            rows.append({"label": name if tree == path or tree == real else f"{name} (worktree)", "path": tree,
                         "branch": branch, "committed": committed, "dirty": len(status),
                         "dirtyMtime": dirty_mtime, "procsHere": procs_here})

    # Newest results: the joint run's and rerun's JUnit in parity/, and Playwright's own
    # `.last-run.json` in any repo's test-results/ — the file a frontend lane's run leaves behind.
    results = []
    if os.path.exists("parity"):
        for f in sorted(os.listdir("parity")):
            if not re.search(r"-(ac|ac-rerun|equiv)\.xml\Z", f):
                continue
            p = os.path.join("parity", f)
            # Skips are counted apart from passes. This used to be total minus failures, which showed a
            # run with 670 of 1209 tests skipped as 1209/1209 passed.
            r = acsuite.read_ac_suite(p)
            if not r or r.get("unreadable"):
                status = "unreadable as JUnit"
            else:
                status = f"{r['passed']}/{r['total']} passed" + (f", {r['failed']} failed" if r["failed"] else "") \
                    + (f", {r['skipped']} skipped" if r["skipped"] else "")
            results.append({"path": p, "mtime": _mtime_ms(p), "status": status})
    for r in rows:
        if r.get("missing"):
            continue
        for p in _find_last_run(r["path"]):
            status = "unreadable"
            try:
                j = json.loads(_read_raw(p))
                if j is None:
                    raise ValueError("null")
                failed = j.get("failedTests") if isinstance(j, dict) else None
                n_failed = len(failed) if isinstance(failed, (list, str)) else 0
                status = f"{_show(j, 'status')}" + (f", {n_failed} failed" if n_failed else "")
            except (ValueError, OSError):
                pass  # reported as unreadable
            results.append({"path": p, "mtime": _mtime_ms(p), "status": status})
    results.sort(key=lambda r: r["mtime"], reverse=True)
    for r in results:
        see_file(r["path"], r["mtime"])

    # Runs driven by run_phases.py. parity/runs/ is gitignored by the driver, so nothing above sees
    # its logs change; they are read here directly.
    runs = []
    runs_dir = os.path.join("parity", "runs")
    if os.path.exists(runs_dir):
        for d in [e for e in _scandir_sorted(runs_dir) if e.is_dir(follow_symlinks=False)]:
            rdir = os.path.join(runs_dir, d.name)
            status = None
            try:
                status = json.loads(_read_raw(os.path.join(rdir, "status.json")))
            except (ValueError, OSError):
                pass  # not started, or not a driver run
            newest = None
            for f in sorted(os.listdir(rdir)):
                try:
                    t = _mtime_ms(os.path.join(rdir, f))
                    if not newest or t > newest["mtime"]:
                        newest = {"path": os.path.join(rdir, f), "mtime": t}
                except OSError:
                    pass  # removed while listing
            if newest:
                see_file(newest["path"], newest["mtime"])
            running = isinstance(status, dict) and status.get("state") == "running"
            alive = bool(running and _truthy(status.get("pid")) and _pid_alive(status.get("pid")))
            runs.append({"dir": rdir, "status": status, "newest": newest, "alive": alive, "died": running and not alive})
        runs.sort(key=lambda r: (r["newest"] or {}).get("mtime") or 0, reverse=True)
    live_runs = [r for r in runs if r["alive"]]
    # A driver that died a day ago was either rerun under a new directory or abandoned, and an
    # old one counted here would make every later check exit 2.
    dead_runs = [r for r in runs if r["died"] and r["newest"] and now - r["newest"]["mtime"] < 24 * 3600000]

    marker_problems = []
    in_progress = _slices_in_progress()
    if in_progress:
        here = os.path.abspath(".")
        for e in _repo_entries()[1:]:
            name, path = e["name"], e["path"]
            if not os.path.exists(path):
                continue
            target = ""
            try:
                target = next((l for l in (_trim(l) for l in _read_text(os.path.join(path, ".rebuild-workbench")).split("\n"))
                               if l and not l.startswith("#")), "")
            except OSError:
                pass  # missing: reported below
            points = os.path.abspath(os.path.join(path, target)) if target else ""
            if not target:
                marker_problems.append(f"{name}: no .rebuild-workbench marker")
            elif not os.path.exists(os.path.join(points, "locks", "pipeline.yaml")):
                marker_problems.append(f"{name}: .rebuild-workbench points at {points}, which is not a workbench")
            elif os.path.realpath(points) != os.path.realpath(here):
                marker_problems.append(f"{name}: .rebuild-workbench points at {points}, not this workbench")

    print(f"lanes-check — {_local_stamp()}\n")
    for r in rows:
        if r.get("missing"):
            print(f"{r['label']}: registered in repos.yaml, path missing ({r['path']})")
            continue
        print(f"{r['label']} [{r['branch']}] — last commit {ago(r['committed'])}, {r['dirty']} dirty" +
              (f" (newest edit {ago(r['dirtyMtime'])})" if r["dirty"] else "") +
              (f", {len(r['procsHere'])} test process(es)" if r["procsHere"] else ""))
    print("")
    if procs is None:
        print("Test processes: could not list processes on this machine — the stall check below is weaker.")
    elif not test_procs:
        print("Test processes: none alive.")
    else:
        print(f"Test processes: {len(test_procs)} alive")
        for p in test_procs[:10]:
            print(f"  {p['pid']}{' (' + p['elapsed'] + ')' if p.get('elapsed') else ''} {p['command'][:140]}")
    if runs:
        print("\nDriven runs (run_phases.py):")
        for r in runs[:5]:
            st = r["status"]
            if not _truthy(st):
                what = "no status.json — not started by run_phases.py"
            elif r["alive"]:
                what = f"running phase {_show(st, 'phase')} (pid {_show(st, 'pid')})"
            elif r["died"]:
                what = f"DRIVER DIED during phase {_show(st, 'phase')} — status says running, pid {_show(st, 'pid')} is gone"
            elif _show(st, "state") == "failed":
                what = f"failed in phase {_show(st, 'phase')}, exit {_show(st, 'exit')}"
            else:
                what = _show(st, "state")
            newest_text = f"{r['newest']['path']}, written {ago(r['newest']['mtime'])}" if r["newest"] else "none"
            print(f"  {r['dir']} — {what}; newest file {newest_text}")
    print("")
    if not results:
        print("Results files: none (parity/*-ac*.xml, Playwright .last-run.json).")
    else:
        print("Newest results:")
        for r in results[:3]:
            print(f"  {r['path']} — written {ago(r['mtime'])}, {r['status']}")

    idle_min = _js_number(opt("--idle", "10"))
    newest = results[0] if results else None
    newest_file = seen["newest"]
    quiet_since = max(last_activity, (newest or {}).get("mtime") or 0, (newest_file or {}).get("mtime") or 0)
    busy = len(test_procs) or len(live_runs)
    stalled = len(dead_runs) or (procs is not None and not busy and quiet_since and (now - quiet_since) / 60000 > idle_min)
    print("")
    if marker_problems:
        print(f"MARKER: {', '.join(in_progress)} in progress, and runbook_guard.py is off for these repos, because it fails open without a marker:")
        for m in marker_problems:
            print(f"  - {m}")
        print(f'  Fix, in each repo: echo "{os.path.abspath(".")}" > .rebuild-workbench && git add .rebuild-workbench && git commit -m "chore: point at the rebuild workbench"\n')
    if stalled:
        if newest and newest["mtime"] >= quiet_since:
            since = f"the newest results file ({newest['path']}, {newest['status']}) was written {ago(newest['mtime'])} and nothing in any repo has changed since"
        else:
            since = f"nothing in any repo or run directory has changed for {ago(quiet_since).replace(' ago', '')}"
        for r in dead_runs:
            print(f"STALLED: the driver for {r['dir']} died during phase {_show(r['status'], 'phase')}; its newest file is {r['newest']['path'] if r['newest'] else 'undefined'}, written {ago(r['newest']['mtime'] if r['newest'] else None)}.")
        if not dead_runs:
            print(f"LOOKS STALLED: no test process alive, and {since}.")
        if newest_file:
            print(f"Newest file anywhere: {newest_file['path']}, written {ago(newest_file['mtime'])}.")
        print("If a lane still has work, send it this evidence and tell it to resume. Heuristic — you decide.")
        return 2
    print("Nothing to act on: a test run is still in progress." if busy
          else f"Nothing to act on: activity within the last {_js_num(idle_min)} min.")
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
    cmd = args[0] if args and args[0] and not args[0].startswith("-") else "check"
    if cmd == "stamp":
        return _stamp(args)
    if cmd != "check":
        print(f'Unknown command "{cmd}". Usage: lanes_check.py [--idle <min>] | stamp [--rerun]', file=sys.stderr)
        return 1
    return _check(args)


if __name__ == "__main__":
    sys.exit(main())
