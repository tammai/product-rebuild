#!/usr/bin/env python3
"""run_phases.py — run a long, several-phase test run as ONE tracked background process.

Run from the workbench root, by the lane that owns the run, with Bash `run_in_background: true`.

  python3 scripts/run_phases.py parity/runs/<local-date>-joint

The directory holds `phases.txt`, written by the lane before it starts:

  # comment
  TEST_DATABASE_URL=postgres://...      # NAME=value: exported to every LATER phase
  reset: cd ../crm-backend && make db-reset
  stamp: python3 scripts/lanes_check.py stamp
  go:    cd ../crm-backend && go test ./... 2>&1 | go-junit-report > ../crm-workbench/parity/<date>-ac-go.xml

Each phase runs in a shell from the workbench root, in order. Output goes to `<phase>.log`, and
`<phase>.done` gets the exit code and duration when the phase ends. `status.json` always says
which phase is running, and the driver's pid, so `lanes_check.py` can tell a live run from a
dead one. The driver stops at the first phase that exits non-zero, and exits with that code.

WHY THIS EXISTS. A joint-run lane stalled three times in one slice, 13 to 18 minutes each:
after the stamp, after the Go suite, after the backend deploy suites. It ran each suite with
`nohup` and watched a done-marker with a Monitor. The harness does not track a `nohup` or `&`
process, so its exit woke nobody, and a Monitor expires after at most 30 minutes, while the suites
took 45 or more. Each hand-off between phases was one more wake-up that could be missed. With
this driver as the lane's one `run_in_background` process, the lane has exactly one wake-up,
when the whole run ends or a phase fails.

WHY `NAME=value` LINES. In the same run, 670 of 1209 backend tests were skipped because the
integration database settings were exported in one shell and the tests ran in another. Every
phase here is its own shell, so an `export` in one phase never reaches the next. A `NAME=value`
line is the one place a setting is given, and every phase after it inherits it.

This is a script, not a paragraph in the brief, because a lane that writes its own driver per
slice writes a different one each time, and lanes_check can only read a layout it knows.

Port notes (this file replaces run-phases.mjs; the observable behaviour is the same):
  - A phase's stdout and stderr go to ONE pipe that the driver copies into the log, and the phase
    ends when its shell has exited AND that pipe has closed. Node's `close` event waited for the
    same two things, so a phase that leaves a background process holding its output keeps the
    driver waiting, exactly as before; a plain file redirect would have returned at once and
    changed what a `&` in a phases.txt does. One merged pipe also keeps stdout and stderr in the
    order they were written, which two Node pipes did not.
  - The driver installs no signal handlers (it only restores the default ones, see main) and
    puts nothing in a new process group, as before:
    a phase's shell shares the driver's group, so a group kill (Ctrl-C, the harness stopping the
    run) reaches both, while a kill of the driver's pid alone leaves status.json saying
    `running` with a dead pid, which is what lanes_check reads as a stall.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

# JavaScript's \s and trim() include U+FEFF and the Unicode spaces; Python's do not include the
# BOM. A phases.txt saved by an editor that writes a BOM must still have its first line read.
_WS = "\t\n\v\f\r    -     　﻿"
_TRIM = re.compile(f"^[{_WS}]+|[{_WS}]+$")
# JavaScript's `.` excludes all four line terminators, Python's only \n; `\w` is ASCII in
# JavaScript and Unicode in Python. A phase named in another script must be refused as before,
# so both are spelled out.
_DOT = "[^\n\r  ]"
_SET = re.compile(rf"([A-Za-z_][A-Za-z0-9_]*)=({_DOT}*)")
_PHASE = re.compile(rf"([A-Za-z0-9][A-Za-z0-9_.-]*):[{_WS}]*({_DOT}+)")


def _join(*parts):
    # Node's path.join normalises ("./x" + "a.log" is "x/a.log"; "a/b/" + ".." is "a"), and the
    # paths printed below and stored in messages are compared by lanes_check as text.
    return os.path.normpath(os.path.join(*parts))


def _iso(now=None):
    # JavaScript's toISOString(): UTC, three millisecond digits, `Z` suffix.
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _write_text(path, text):
    # newline="\n": Windows would otherwise turn every LF into CRLF.
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def parse_phases(text):
    """Returns (phases, problems). A phase is {"set", "value"} or {"name", "command"}."""
    phases, problems = [], []
    # Split on CRLF or LF only, as the JavaScript did: a lone CR is not a line break here, and
    # it would be the one place a stray character from an old editor changed the meaning.
    for i, raw in enumerate(re.split(r"\r?\n", text)):
        line = _TRIM.sub("", raw)
        if not line or line.startswith("#"):
            continue
        m = _SET.fullmatch(line)
        if m:
            phases.append({"set": m.group(1), "value": m.group(2)})
            continue
        m = _PHASE.fullmatch(line)
        if m:
            phases.append({"name": m.group(1), "command": m.group(2)})
            continue
        problems.append(f'line {i + 1}: neither "NAME=value" nor "phase: command" — {line}')
    return phases, problems


def _spawn(command, env):
    """Start `command` in a shell with stdin closed and stdout+stderr on one pipe."""
    kwargs = dict(env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if os.name == "nt":
        # Node's `shell: true` runs `cmd.exe /d /s /c "<command>"` with the command line passed
        # verbatim. Python's shell=True omits /d (the AutoRun registry hook) and /s (which makes
        # cmd strip exactly the outer quotes), so a command with its own quotes parsed differently.
        # A single string is handed to CreateProcess untouched; a list would be re-quoted.
        comspec = os.environ.get("comspec") or "cmd.exe"
        return subprocess.Popen(f'{comspec} /d /s /c "{command}"', shell=False, **kwargs)
    return subprocess.Popen(command, shell=True, **kwargs)


def _run_phase(directory, p, env):
    t0 = int(time.time() * 1000)
    with open(_join(directory, f"{p['name']}.log"), "wb") as log:
        child = _spawn(p["command"], env)
        # Copy until the pipe closes, flushing per chunk: a lane tails this file while the phase
        # runs, and a buffered log looks like a hung phase.
        while True:
            chunk = os.read(child.stdout.fileno(), 65536)
            if not chunk:
                break
            log.write(chunk)
            log.flush()
        child.stdout.close()
        code = child.wait()
    # A command the shell cannot start still ends here, with code 127 or 1, so this has one
    # exit path. A signal-killed phase (a negative return code in Python, a null `code` in
    # Node) counts as a failure.
    signal_name = None
    if code < 0 and os.name != "nt":
        try:
            signal_name = signal.Signals(-code).name
        except ValueError:
            signal_name = f"SIG{-code}"
        code = None
    exit_code = 128 if code is None else code
    seconds = _js_round((int(time.time() * 1000) - t0) / 1000)
    _write_text(_join(directory, f"{p['name']}.done"),
                f"exit={exit_code}{' signal=' + signal_name if signal_name else ''} seconds={seconds}\n")
    return {"phase": p["name"], "exit": exit_code, "seconds": seconds}


def _js_round(x):
    # Math.round: halves go up. Python's round() goes to even, so a 2.5 s phase would be "2s"
    # here and "3s" in the .done file the lanes read.
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            # newline="\n": Node's console.log writes a bare LF on Windows too.
            s.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        except Exception:
            pass
    args = list(sys.argv[1:] if argv is None else argv)

    # Node resets every signal to its default disposition at startup, including one the launching
    # shell had ignored (a `&` job or `nohup` ignores SIGINT and SIGHUP), so under Node a
    # `kill -INT` on the driver always killed it. Python would instead raise KeyboardInterrupt
    # (a traceback and cleanup) for SIGINT and leave an inherited "ignore" in place for the rest.
    # Restoring the defaults keeps the one behaviour lanes_check relies on: a signalled driver
    # dies at once and leaves status.json saying `running` with a dead pid.
    for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGQUIT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_DFL)

    if not os.path.exists(_join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    directory = args[0] if args else None
    if not directory or not os.path.exists(_join(directory, "phases.txt")):
        print("Usage: python3 scripts/run_phases.py <run dir>  — the directory must hold phases.txt.\n"
              "Convention: parity/runs/<local-date>-<label>, e.g. parity/runs/2026-10-06-joint.",
              file=sys.stderr)
        return 1

    # Logs can run to hundreds of megabytes and say nothing a JUnit file does not. Written here, not
    # by rebuild_init, so workbenches scaffolded before this script existed ignore them too.
    runs_root = _join(directory, "..")
    if not os.path.exists(_join(runs_root, ".gitignore")):
        os.makedirs(runs_root, exist_ok=True)
        _write_text(_join(runs_root, ".gitignore"), "*\n")

    env = dict(os.environ)
    # newline="": keep the file's own line endings so the split below sees exactly what the
    # JavaScript saw.
    with open(_join(directory, "phases.txt"), encoding="utf-8", errors="replace", newline="") as f:
        phases, problems = parse_phases(f.read())
    names = [p["name"] for p in phases if p.get("name")]
    seen, dup = set(), []
    for n in names:
        if n in seen and n not in dup:
            dup.append(n)
        seen.add(n)
    if dup:
        problems.append(f"phase names repeat ({', '.join(dup)}): each one names its log and .done file")
    if not names:
        problems.append("no phases")
    if problems:
        print(f"{_join(directory, 'phases.txt')} is not usable:\n" + "\n".join(f"  - {p}" for p in problems),
              file=sys.stderr)
        return 1

    started = _iso()
    results = []

    def write_status(**fields):
        _write_text(_join(directory, "status.json"), json.dumps({
            "pid": os.getpid(), "started": started, "updated": _iso(), "phases": names,
            "results": results, **fields,
        }, indent=2, ensure_ascii=False) + "\n")

    for p in phases:
        if p.get("set"):
            env[p["set"]] = p["value"]
            continue
        write_status(state="running", phase=p["name"])
        r = _run_phase(directory, p, env)
        results.append(r)
        print(f"{'ok  ' if r['exit'] == 0 else 'FAIL'}  {r['phase']} — exit {r['exit']}, {r['seconds']}s, "
              f"log {_join(directory, r['phase'] + '.log')}")
        if r["exit"] != 0:
            write_status(state="failed", phase=p["name"], exit=r["exit"])
            skipped = names[names.index(p["name"]) + 1:]
            if skipped:
                print(f"Not run, because {p['name']} failed: {', '.join(skipped)}")
            sys.stdout.flush()
            return r["exit"]
    write_status(state="passed", phase=None, exit=0)
    print(f"All {len(names)} phase(s) passed. Read the JUnit each one wrote, skips included, before reporting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
