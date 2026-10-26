#!/usr/bin/env python3
"""autopilot.py — run-state and safety checks for unattended pipeline stretches.

Run from the workbench root.

Usage:
  python3 scripts/autopilot.py preflight [--threshold 80] [--context-tokens 250000]
  python3 scripts/autopilot.py check
  python3 scripts/autopilot.py engage [--threshold 80] [--context-tokens 250000] [--phase "..."]
  python3 scripts/autopilot.py log --unit "..." --outcome done|failed|skipped [--note "..."]
  python3 scripts/autopilot.py disengage --reason <r> [--next "..."]
  python3 scripts/autopilot.py status

Autopilot never touches a gate. It runs the mechanical stretches BETWEEN gates and halts
at each one; locking stays a human act (SKILL.md Step 5).

It is a script, not a paragraph in a brief, because the numbers it enforces (the 5-hour window,
the context size) are visible only to the status line, and an unattended run that was merely
TOLD to watch them would watch nothing. A script can refuse to proceed when it cannot read them.

Standard library only, same fixed YAML subset as gate.py and pause_check.py.

Port notes (this file replaces autopilot.mjs; the helpers below exist because JavaScript and
Python disagree on small things that this script's output depends on):
  - `_js_number` / `_js_str` / `_js_round` reproduce Number(), String() and Math.round(): Python's
    round() is banker's rounding (round(2.5) == 2, JavaScript says 3), float("1_0") is 10 where
    Number("1_0") is NaN, float("nan") is truthy where NaN is falsy, and 80.0 prints as "80.0"
    where JavaScript prints "80". Each shows up in state files or messages, so each is handled.
  - Timestamps are written as JavaScript's toISOString() does: UTC, milliseconds, a `Z` suffix.
  - There is no node_modules check in `preflight`: a Python workbench vendors yamlio.py and
    schemacheck.py inside scripts/, so there is nothing to install.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

STATE = os.path.join("plan", "autopilot.yaml")
DEFAULT_THRESHOLD = 80

# Where the status line drops its snapshot. The 5-hour and 7-day windows are piped by Claude
# Code to the STATUS LINE ONLY — not to hooks, not to the model — so the only way anything
# here can see them is if the status line has been patched to persist them. Overridable so
# the behaviour at 0%, 85% and "stale" can actually be tested.
SNAPSHOT = os.environ.get("REBUILD_RATE_LIMITS") or os.path.join(
    os.path.expanduser("~"), ".claude", ".rate-limits.json")

# A snapshot older than this is treated as no snapshot at all.
#
# 15 minutes is safe HERE specifically because `check` runs at unit boundaries. The status
# line re-renders at tool-call boundaries, not during a call (measured: one 100-second call
# saw updates at each end and a 95-second silence between), so by the time `check` runs a
# render has just happened. The guard hook can fire mid-call — a subagent writing findings
# twenty minutes into a slice build — so it uses a far looser bound for the same reason.
# See hooks/scripts/autopilot_guard.py.
MAX_SNAPSHOT_AGE_S = 900

# The orchestrator's own context, in tokens, and the size at which a run halts at the next unit
# boundary so the user can start a fresh session.
#
# Cost here is context re-read on every turn, not output: one audited run held a ~445k median
# context for 5,000 turns, and one autopilot session spent 181M tokens. "One session per unit"
# was already the rule (SKILL.md, Context hygiene), but autopilot was the one mode that never
# ended a session, and it can't clear its own context, so the run has to stop and ask.
#
# Like the 5-hour window, the number is only visible to the status line (it gets
# `transcript_path`), so it is read from a snapshot the status line writes per directory
# (references/autopilot.md has the block). Unlike the window, a missing snapshot FAILS OPEN:
# this is hygiene, not a safety limit, and refusing to run without it would break every
# setup that predates the block.
CONTEXT_DIR = os.environ.get("REBUILD_CONTEXT_DIR") or os.path.join(
    os.path.expanduser("~"), ".claude", ".context")
DEFAULT_CONTEXT_TOKENS = 250000

REASONS = [
    "usage-threshold", "context-threshold", "gate-review", "validate-failed",
    "pause-check-unsafe", "needs-user-decision", "error", "user",
]
OUTCOMES = ["done", "failed", "skipped"]

# JavaScript's \s and trim() also cover U+FEFF and the Unicode spaces; Python's differ at the
# edges (Python adds \x1c-\x1f, drops U+FEFF). A state file edited by hand in an editor that
# writes a BOM is exactly where the difference would show, so the class is spelled out.
_WS = "\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_TRIM = re.compile(f"^[{_WS}]+|[{_WS}]+$")

# Absent in JSON or in an argument list. Kept apart from None, which is JSON null: Number(null)
# is 0 while Number(undefined) is NaN, and `used_percentage: null` must not read as "usage 0%".
_UNDEF = object()


def read_text(path):
    # CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the
    # working copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently
    # matches nothing — read as "no such block" rather than an error. Same helper in every
    # script that parses text; copied, not imported, because each is vendored and must run
    # alone. See playbook.py's read_text for the incident.
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


def _write_text(path, text):
    # newline="\n": Windows would otherwise turn every LF into CRLF and the next read_text
    # would have to undo it.
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _js_trim(s):
    return _TRIM.sub("", s)


_DECIMAL = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def _normalise(x):
    # An integral float is an int: it prints as "80", not "80.0", the way a JS number does.
    if isinstance(x, float) and math.isfinite(x) and x == int(x) and abs(x) < 2 ** 53:
        return int(x)
    return x


def _js_number(v):
    """Number(v) for the value shapes this script meets: JSON scalars and argv strings."""
    if v is _UNDEF:
        return math.nan
    if v is None:
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return _normalise(v)
    if isinstance(v, str):
        s = _js_trim(v)
        if s == "":
            return 0
        if re.fullmatch(r"0[xX][0-9a-fA-F]+", s):
            return int(s, 16)
        if re.fullmatch(r"0[oO][0-7]+", s):
            return int(s[2:], 8)
        if re.fullmatch(r"0[bB][01]+", s):
            return int(s[2:], 2)
        if re.fullmatch(r"[+-]?Infinity", s):
            return -math.inf if s[0] == "-" else math.inf
        if _DECIMAL.fullmatch(s):
            return _normalise(float(s))
        return math.nan
    if isinstance(v, list):
        if not v:
            return 0
        return _js_number(v[0]) if len(v) == 1 and not isinstance(v[0], (list, dict)) else math.nan
    return math.nan


def _js_str(v):
    """String(v), as a template literal would print it."""
    if v is _UNDEF:
        return "undefined"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        if v == int(v) and abs(v) < 1e21:
            return str(int(v))
        return re.sub(r"e([+-])0+([0-9])", r"e\1\2", repr(v))
    if isinstance(v, list):
        return ",".join("" if x is None else _js_str(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


def _u(v):
    # A field read from the state file is None when the file lacks it; JavaScript printed
    # that as "undefined", and a hand-edited file is the only way to meet it.
    return "undefined" if v is None else _js_str(v)


def _js_round(x):
    """Math.round: halves go UP (2.5 -> 3, -2.5 -> -2). Python's round() goes to even."""
    if isinstance(x, float) and not math.isfinite(x):
        return x
    return math.floor(x + 0.5)


def _truthy_number(n):
    return n if isinstance(n, (int, float)) and n == n and n != 0 else None


def _iso_now():
    # JavaScript's toISOString(): UTC, always three millisecond digits, `Z` suffix. Python's
    # isoformat() would give "+00:00" and microseconds, and the state file's `at` values are
    # compared and displayed as written.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _now_s():
    return int(time.time())


# --- YAML subset (same rules as gate.py) ---------------------------------------------------
_NEEDS_QUOTING = re.compile(
    rf": |:\Z|^[-?:,\[\]{{}}#&*!|>'\"%@`]|\n|^[{_WS}]|[{_WS}]\Z")


def _yaml_str(s):
    s = _js_str(s)
    if _NEEDS_QUOTING.search(s):
        return '"' + s.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"') + '"'
    return s


def _unquote(s):
    if s is not None and re.fullmatch(r'".*"', s):
        return s[1:-1].replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
    return s


def _arg_after(args, flag):
    if flag not in args:
        return None
    i = args.index(flag)
    return args[i + 1] if i + 1 < len(args) else None


def _arg_number(args, flag):
    """`Number(argAfter(flag)) || undefined`: a missing, unparsable or zero value is "not given"."""
    v = _arg_after(args, flag)
    return _truthy_number(_js_number(_UNDEF if v is None else v))


# --- State file ------------------------------------------------------------------------
# Read into a plain object and rewrite whole on every mutation, exactly like gate.py does
# with a lock file. Nothing else writes this file, so round-tripping a fixed shape is safe.
def read_state():
    if not os.path.exists(STATE):
        return None
    text = read_text(STATE)

    def top(k):
        m = re.search(rf"^{k}: (.*)$", text, re.M)
        return _unquote(_js_trim(m.group(1))) if m else None

    def block(name):
        m = re.search(rf"^{name}:\n((?:  [^ \n].*\n?)*)", text, re.M)
        if not m:
            return None
        out = {}
        for line in re.finditer(r"^  ([a-z_]+): (.*)$", m.group(1), re.M):
            out[line.group(1)] = _unquote(_js_trim(line.group(2)))
        return out

    log = []
    log_block = re.search(rf"^log:\n((?:(?:[ \t]+.*)?\n)*)", text, re.M)
    if log_block:
        for chunk in re.split(r"^  - ", log_block.group(1), flags=re.M)[1:]:
            e = {}
            for line in re.finditer(r"^(?:  - |    )([a-z_]+): (.*)$", "  - " + chunk, re.M):
                e[line.group(1)] = _unquote(_js_trim(line.group(2)))
            if e:
                log.append(e)
    top_threshold = top("threshold_pct")
    top_context = top("context_tokens")
    return {
        "status": top("status"),
        "engaged_at": top("engaged_at"),
        "engaged_phase": top("engaged_phase"),
        "threshold_pct": _truthy_number(_js_number(_UNDEF if top_threshold is None else top_threshold))
                         or DEFAULT_THRESHOLD,
        "context_tokens": _truthy_number(_js_number(_UNDEF if top_context is None else top_context)),
        "stop_at_gates": top("stop_at_gates") != "false",
        "last_check": block("last_check"),
        "paused": block("paused"),
        "log": log,
    }


def write_state(s):
    os.makedirs("plan", exist_ok=True)
    lines = [
        "# Autopilot run state. Mutable and ungated — no gate protects plan/.",
        "# BREADCRUMBS, NOT TRUTH: on resume, re-derive the real phase from",
        "# `python3 scripts/gate.py status`. Never act on engaged_phase or paused.next_action alone.",
        "# Written by scripts/autopilot.py — do not edit by hand.",
        f"status: {_u(s.get('status'))}",
    ]
    if s.get("engaged_at"):
        lines.append(f"engaged_at: {s['engaged_at']}")
    if s.get("engaged_phase"):
        lines.append(f"engaged_phase: {_yaml_str(s['engaged_phase'])}")
    lines.append(f"threshold_pct: {_u(s.get('threshold_pct'))}")
    if s.get("context_tokens"):
        lines.append(f"context_tokens: {_js_str(s['context_tokens'])}")
    lines.append(f"stop_at_gates: {'false' if s.get('stop_at_gates') is False else 'true'}")

    def sub(name, obj):
        # `is None`, not falsiness: a block that parsed to an empty dict is still a block, and
        # the JavaScript wrote its header line.
        if obj is None:
            return
        lines.append(f"{name}:")
        for k, v in obj.items():
            if v is None or v == "":
                continue
            is_number = isinstance(v, (int, float)) and not isinstance(v, bool)
            lines.append(f"  {k}: {_js_str(v) if is_number else _yaml_str(v)}")

    sub("last_check", s.get("last_check"))
    sub("paused", s.get("paused"))
    # `log:` with nothing under it parses as null, not [] — which fails the schema on every
    # freshly engaged run, before a single unit has been logged.
    entries = s.get("log") or []
    lines.append("log:" if entries else "log: []")
    for e in entries:
        lines.append(f"  - at: {_u(e.get('at'))}")
        for k in ("unit", "outcome", "note"):
            if e.get(k) is not None and e.get(k) != "":
                lines.append(f"    {k}: {_yaml_str(e[k])}")
    _write_text(STATE, "\n".join(lines) + "\n")


def commit_state(msg):
    """Commit the state file on every mutation, and only ever this one path.

    Not tidiness: `gate.py lock` refuses to run while the working tree is dirty outside the
    lock file, because hashes computed from a dirty tree describe content the gate tag will
    not contain. Autopilot halts AT a gate and hands over to the user to lock — so leaving
    plan/autopilot.yaml uncommitted would make the very next thing the user does fail. Commit
    it here so the handover lands on a clean tree.

    An argument list, not a shell string: `msg` carries a unit label the model wrote, and a slice
    name containing a quote or a backtick would otherwise be interpolated straight into a
    shell command by the one script that runs unattended.
    """
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, stdin=subprocess.DEVNULL)

    try:
        if git("add", "--", STATE).returncode != 0:
            return
        # Exit 0 from --quiet means no staged change; anything else falls through to commit,
        # as the JavaScript did (exit 1 is the real "there is one").
        if git("diff", "--cached", "--quiet", "--", STATE).returncode == 0:
            return
        git("commit", "-qm", f"autopilot: {msg}")
    except OSError:
        pass  # git unavailable — never fatal


# --- Usage snapshot ----------------------------------------------------------------------
def _twelve_hour_locale():
    # Node's toLocaleTimeString([]) follows the environment's locale: "03:26 AM" for en-US
    # (and for an unset or C locale, which Node reads as en-US), "03:26" for en-GB, de, fr, ja,
    # vi. Python does not call setlocale here, so the choice is made from the same variables in
    # the order the C library uses. The 12-hour set is the common English locales only; a
    # locale outside it prints 24-hour, which can differ from Node for a rarer 12-hour locale.
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var)
        if v:
            loc = re.split(r"[.@]", v)[0]
            break
    else:
        loc = "C"
    return loc in ("C", "POSIX", "") or loc in (
        "en_US", "en_CA", "en_AU", "en_NZ", "en_IN", "en_PH")


def clock(epoch):
    t = time.localtime(epoch)
    return time.strftime("%I:%M %p" if _twelve_hour_locale() else "%H:%M", t)


def human_in(seconds):
    if seconds <= 0:
        return "now"
    h = math.floor(seconds / 3600)
    m = _js_round((seconds % 3600) / 60)
    return f"{h}h {m}m" if h else f"{m}m"


def _get(d, *keys):
    """JavaScript's `d?.a?.b`: _UNDEF for anything missing or not an object."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return _UNDEF
        cur = cur[k]
    return cur


def _load_json(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def read_usage():
    """Returns {ok, pct, resets_at, reason} — `ok: False` means the number could not be
    established, which is never the same thing as "usage is low"."""
    if not os.path.exists(SNAPSHOT):
        return {"ok": False, "reason":
                f"no usage snapshot at {SNAPSHOT}.\n"
                "  The 5-hour window is piped only to the status line, so it has to be persisted there.\n"
                "  Add the snapshot block to your statusLine command (see references/autopilot.md), or —\n"
                "  if you are not on a Claude Pro/Max plan — the field does not exist and autopilot\n"
                "  cannot watch the window at all."}
    try:
        snap = _load_json(SNAPSHOT)
    except Exception:
        return {"ok": False, "reason": f"usage snapshot at {SNAPSHOT} is unreadable."}
    at = _get(snap, "at")
    age = _now_s() - _js_number(0 if at is _UNDEF or at in (None, "", 0, False) else at)
    if not (isinstance(age, (int, float)) and math.isfinite(age)) or age > MAX_SNAPSHOT_AGE_S:
        shown = "NaN" if isinstance(age, float) and math.isnan(age) else _js_str(_js_round(age / 60))
        return {"ok": False, "reason":
                f"usage snapshot is stale ({shown}m old, limit {MAX_SNAPSHOT_AGE_S // 60}m).\n"
                "  The status line re-renders constantly in a live session, so a stale snapshot means\n"
                "  renders have stopped — autopilot is interactive-session only."}
    pct = _js_number(_get(snap, "five_hour", "used_percentage"))
    if not (isinstance(pct, (int, float)) and math.isfinite(pct)):
        return {"ok": False, "reason":
                "usage snapshot has no five_hour.used_percentage.\n"
                "  This field exists only for Claude Pro/Max plans, and only after the session's first\n"
                "  API response."}
    resets = _js_number(_get(snap, "five_hour", "resets_at"))
    return {"ok": True, "pct": pct, "resets_at": _truthy_number(resets) or 0,
            "seven_day": _js_number(_get(snap, "seven_day", "used_percentage"))}


def usage_line(u):
    resets = (f" — window resets {clock(u['resets_at'])} (in {human_in(u['resets_at'] - _now_s())})"
              if u["resets_at"] else "")
    seven = u["seven_day"]
    week = f", 7d {_js_round(seven)}%" if isinstance(seven, (int, float)) and math.isfinite(seven) else ""
    return f"5h usage {_js_round(u['pct'])}%{week}{resets}"


def _slug(directory):
    # [^A-Za-z0-9] over UTF-16 code units in the JavaScript, so a character outside the Basic
    # Multilingual Plane (an emoji in a directory name) became TWO dashes. The status line
    # computes the same slug when it names the snapshot file, so the count has to match.
    return re.sub(r"[^A-Za-z0-9]", lambda m: "--" if ord(m.group()) > 0xFFFF else "-", directory)


def read_context():
    """The snapshot is keyed by directory, not session: autopilot cannot learn its own session id.
    The status line writes one for the session's current dir and one for its project dir; this
    walks up from the workbench root and takes the freshest match, which covers a session
    started in the workbench or in a parent of it. Two live sessions in the same directory
    overwrite each other, and the freshest wins."""
    best = None
    directory = os.path.abspath(".")
    while True:
        f = os.path.join(CONTEXT_DIR, f"{_slug(directory)}.json")
        if os.path.exists(f):
            try:
                snap = _load_json(f)
                at = _get(snap, "at")
                tokens = _js_number(_get(snap, "tokens"))
                age = _now_s() - _js_number(0 if at is _UNDEF or at in (None, "", 0, False) else at)
                if (isinstance(tokens, (int, float)) and math.isfinite(tokens)
                        and age <= MAX_SNAPSHOT_AGE_S
                        and (best is None or at > best["at"])):
                    best = {**snap, "tokens": tokens}
            except Exception:
                pass  # unreadable: treat as absent
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    if best is None:
        return {"ok": False, "reason":
                f"no fresh context snapshot under {CONTEXT_DIR} for this directory "
                "or a parent (add the context block to your statusLine command — references/autopilot.md)"}
    return {"ok": True, "tokens": best["tokens"], "dir": best.get("dir")}


def k_tok(n):
    return f"{_js_round(n / 1000)}k"


def context_limit_of(args, state):
    return (_arg_number(args, "--context-tokens")
            or (state or {}).get("context_tokens") or DEFAULT_CONTEXT_TOKENS)


def threshold_of(args, state):
    return (_arg_number(args, "--threshold")
            or (state or {}).get("threshold_pct") or DEFAULT_THRESHOLD)


def _run_script(script, *args):
    """Run a sibling script and return (exit_ok, stdout). stderr is inherited, as it was for
    execFileSync, so a sibling's own complaint still reaches the user; stdin is closed so a
    sibling can never block an unattended run waiting for a keystroke."""
    r = subprocess.run([sys.executable, "scripts/" + script, *args], stdout=subprocess.PIPE,
                       stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    return r.returncode == 0, r.stdout


def _first_line(e):
    return str(e).split("\n")[0]


def _gate_phase(out):
    m = re.search(r"^Current phase: (.+?) \(working toward", out, re.M)
    return m.group(1) if m else None


# --- Commands ------------------------------------------------------------------------
def cmd_check(args, state):
    # Deliberately read-only and fast: safe to call before every unit of work, and it never
    # dirties the tree. `last_check` is stamped by engage/log/disengage instead.
    #
    # Conservative where the guard hook is permissive: an unverifiable snapshot exits 3 here
    # (only autopilot calls this) but is ignored by hooks/scripts/autopilot_guard.py, which
    # must never break an unrelated edit.
    threshold = threshold_of(args, state)
    u = read_usage()
    if not u["ok"]:
        print(f"PAUSE  cannot verify usage — {u['reason']}")
        return 3
    if u["pct"] >= threshold:
        print(f"PAUSE  {usage_line(u)} — at or over the {_js_str(threshold)}% threshold.")
        print("       Run the pause procedure: save, commit, push, disengage, pause-check.")
        return 3
    limit = context_limit_of(args, state)
    c = read_context()
    if c["ok"] and c["tokens"] >= limit:
        print(f"PAUSE  context {k_tok(c['tokens'])} tokens — at or over the {k_tok(limit)} limit.")
        print("       Finish nothing new. Run the pause procedure with --reason context-threshold,")
        print("       then tell the user: /clear, then /rebuild to resume in a fresh session.")
        return 3
    print(f"OK     {usage_line(u)} · threshold {_js_str(threshold)}%")
    print(f"       context {k_tok(c['tokens'])} tokens · limit {k_tok(limit)}" if c["ok"]
          else f"       context unknown — {c['reason']}")
    return 0


def cmd_preflight(args, state):
    threshold = threshold_of(args, state)
    blockers, notes = [], []

    # 1. Phase must be derivable, and there must be something left to do.
    phase = None
    ok, out = _run_script("gate.py", "status")
    if ok:
        notes.append("gate.py status:\n" + "\n".join(f"    {l}" for l in out.strip().split("\n")))
        if re.search(r"All gates locked", out):
            blockers.append("pipeline is complete — all five gates are locked.")
        phase = _gate_phase(out)
        if not phase and not re.search(r"All gates locked", out):
            blockers.append("gate.py status did not report a current phase.")
    else:
        blockers.append("gate.py status failed: Command failed: python3 scripts/gate.py status")

    # 1b. The G0 preflight (preflight.json). An unattended run's first act at G1 is to
    #     dispatch miners at every lane in parallel, and a wrong `pinned_commit` makes every
    #     lane-D citation they write wrong — silently, because a finding's hash is of the
    #     finding, not of the thing it describes. That is the one failure an unattended run
    #     cannot notice and cannot undo cheaply: by the time a human reads it, a gate has
    #     hashed it. So Not-ready is a blocker here and not a note.
    #
    #     Absent is NOT a blocker. Every workbench scaffolded before 0.16.0 has no
    #     preflight.json and no scripts/preflight.py, and refusing to run unattended on that
    #     basis would break every existing project the day this shipped, for a check that has
    #     never run for them anyway.
    if not os.path.exists("preflight.json"):
        notes.append("no preflight.json — this workbench predates 0.16.0 or has not run `python3 scripts/preflight.py`.\n"
                     "    G0's reference check is the user's word, as it was before. Copy scripts/preflight.py\n"
                     "    and schemas/preflight.schema.json from the plugin to get the real one (docs/PLAYBOOK.md).")
    else:
        pf = None
        try:
            pf = _load_json("preflight.json")
        except Exception as e:
            blockers.append(f"preflight.json is unreadable ({_first_line(e)}) — re-run `python3 scripts/preflight.py`.")
        # `{}` and `[]` are truthy in JavaScript and falsy in Python; only null, false, 0 and ""
        # skip this block, and an empty object lands on "no recognised verdict (undefined)".
        if pf is not None and pf is not False and pf != 0 and pf != "":
            lanes = _get(pf, "lanes")
            lane_line = " · ".join(f"{k}:{_js_str(v)}" for k, v in lanes.items()) if isinstance(lanes, dict) else ""
            verdict = _get(pf, "verdict")
            if verdict == "Not-ready":
                bl = _get(pf, "blockers")
                blockers.append("G0 preflight reads Not-ready — G1 must not dispatch miners:\n" +
                                "\n".join(f"      - {_js_str(b)}" for b in (bl if isinstance(bl, list) else [])) +
                                "\n      Fix the cause and re-run `python3 scripts/preflight.py`. PREFLIGHT.md has the detail.")
            elif verdict == "Ready-with-gaps":
                gaps = _get(pf, "gaps")
                notes.append(f"preflight: 🟡 Ready-with-gaps (lanes {lane_line}) — mining may start; the gaps are named "
                             "in PREFLIGHT.md:\n" +
                             "\n".join(f"    - {_js_str(g)}" for g in (gaps if isinstance(gaps, list) else [])))
            elif verdict == "Ready":
                notes.append(f"preflight: ✅ Ready (lanes {lane_line}).")
            else:
                blockers.append(f"preflight.json carries no recognised verdict ({_js_str(verdict)}) — re-run `python3 scripts/preflight.py`.")

    # 2b. The model ladder. A malformed .claude/model-routing.json degrades to the balanced
    #     default rather than failing, which is right for an attended dispatch — the orchestrator
    #     relays the warning and the user sees it. Unattended there is nobody to relay to, and a
    #     whole run's worth of dispatches on a silently-defaulted ladder is exactly the kind of
    #     thing you find out about from the bill. So surface it here, as a NOTE and never a
    #     blocker: the default is a working configuration, just not the one the file asked for.
    if not os.path.exists(os.path.join("scripts", "routing.py")):
        notes.append("no scripts/routing.py — this workbench predates 0.16.0, so the model ladder is\n"
                     "    resolved from the plugin's copy instead (SKILL.md 4b has the command). Nothing to fix.")
    else:
        try:
            ok, out = _run_script("routing.py")
            if not ok:
                raise RuntimeError("Command failed: python3 scripts/routing.py")
            r = json.loads(out)
            warnings = r.get("warnings")
            real = [w for w in (warnings if warnings is not None else []) if not re.search("effort", w, re.I)]
            if real:
                notes.append("model ladder has warnings — dispatches will run on the resolved values below, not the file's:\n" +
                             "\n".join(f"    - {w}" for w in real))
            notes.append(f"model ladder: {_u(r.get('profile'))} ({_u(r.get('profileSource'))}) — " +
                         " · ".join(f"{k}:{_u(v.get('model'))}" for k, v in r["roles"].items()))
        except Exception as e:
            notes.append(f"could not resolve the model ladder ({_first_line(e)}) — "
                         "dispatches will fall back to whatever model the session runs on.")

    # 3. Everything a session-end check already covers: dirty trees, unpushed work across
    #    repos.yaml, stashes, gates reopened but not re-locked, stray services. Reuse it
    #    rather than reimplementing any of it.
    if not os.path.exists(os.path.join("scripts", "pause_check.py")):
        blockers.append("scripts/pause_check.py is missing — copy it from the plugin's skills/rebuild-pipeline/scripts/.")
    else:
        # A non-zero exit still carries a verdict on stdout, so the exit code is not consulted.
        _, pc = _run_script("pause_check.py")
        if re.search(r"NOT safe to pause", pc):
            blockers.append("pause-check reports the workbench is NOT in a safe state:\n" +
                            "\n".join(f"      {_js_trim(l)}" for l in pc.split("\n")
                                      if re.search(rf"^[{_WS}]+- ", l)))
        elif re.search(r"Safe to pause as far as could be checked", pc):
            notes.append("pause-check: 🟡 clean, but a remote was unreachable — unpushed tags could not be ruled out.")
        elif re.search(r"Safe to pause", pc):
            notes.append("pause-check: ✅ clean.")
        else:
            blockers.append("pause-check produced no verdict — resolve that before running unattended.")

    # 4. The usage signal itself.
    u = read_usage()
    if not u["ok"]:
        blockers.append(u["reason"])
    else:
        notes.append(f"usage: {usage_line(u)}")
        if u["pct"] >= threshold:
            blockers.append(f"5h usage is already {_js_round(u['pct'])}%, at or over the {_js_str(threshold)}% threshold" +
                            (f" — the window resets {clock(u['resets_at'])}." if u["resets_at"] else "."))

    # 4b. The session's own context. Starting a run in a session that is already large means
    #     every unit pays for it; a fresh session is one /clear away.
    limit = context_limit_of(args, state)
    c = read_context()
    if not c["ok"]:
        notes.append(f"context: unknown — {c['reason']}. The run will not halt on context size.")
    else:
        notes.append(f"context: {k_tok(c['tokens'])} tokens · limit {k_tok(limit)}")
        if c["tokens"] >= limit:
            blockers.append(f"this session's context is already {k_tok(c['tokens'])} tokens, over the {k_tok(limit)} limit — "
                            "/clear and run /rebuild in a fresh session before engaging.")

    # 5. A run left engaged by a session that died.
    if state and state.get("status") == "engaged":
        notes.append("NOTE: plan/autopilot.yaml still says `engaged` — a previous run ended without "
                     "disengaging. Re-engaging will overwrite it; its log is preserved.")
    if state and state.get("status") == "paused" and state.get("paused") is not None:
        paused = state["paused"]
        notes.append(f"previous run paused ({_u(paused.get('reason'))})" +
                     (f"; next_action was: {paused['next_action']}" if paused.get("next_action") else "") +
                     "\n    Treat that as a hint only — the phase above is the authority.")

    print("Autopilot preflight\n")
    for n in notes:
        print(f"  {n}")
    if blockers:
        print("\n⛔ NOT ready for autopilot:")
        for b in blockers:
            print(f"  - {b}")
        print("\nResolve these, then re-run preflight. Do not engage on a partial pass.")
        return 1
    print(f"\n✅ Ready for autopilot at: {phase}")
    print(f"   Threshold {_js_str(threshold)}% of the 5-hour window; context limit {k_tok(limit)} tokens.")
    print("   Gates still halt for the user.")
    print("   Present the brief and get explicit confirmation before engaging.")
    return 0


def cmd_engage(args, state):
    threshold = _arg_number(args, "--threshold") or DEFAULT_THRESHOLD
    u = read_usage()
    if not u["ok"]:
        print(f"Cannot engage: {u['reason']}", file=sys.stderr)
        return 1
    if u["pct"] >= threshold:
        print(f"Cannot engage: {usage_line(u)} is already at or over the {_js_str(threshold)}% threshold.", file=sys.stderr)
        return 1
    limit = _arg_number(args, "--context-tokens") or DEFAULT_CONTEXT_TOKENS
    c = read_context()
    if c["ok"] and c["tokens"] >= limit:
        print(f"Cannot engage: context is {k_tok(c['tokens'])} tokens, over the {k_tok(limit)} limit — /clear first.", file=sys.stderr)
        return 1
    phase = _arg_after(args, "--phase")
    if not phase:
        ok, out = _run_script("gate.py", "status")
        if ok:
            phase = _gate_phase(out)  # a failure is recorded as unknown below
    now = _iso_now()
    write_state({
        "status": "engaged",
        "engaged_at": now,
        "engaged_phase": phase or "unknown",
        "threshold_pct": threshold,
        "context_tokens": limit,
        "stop_at_gates": True,
        "last_check": {"at": now, "five_hour_pct": _js_round(u["pct"]), "resets_at": u["resets_at"],
                       "context_tokens": c["tokens"] if c["ok"] else None},
        "paused": None,
        "log": (state or {}).get("log") or [],
    })
    commit_state(f"engaged at {phase or 'unknown'}")
    print(f"Autopilot ENGAGED at: {phase or 'unknown'}")
    print(f"  {usage_line(u)} · threshold {_js_str(threshold)}% · context limit {k_tok(limit)}")
    print("  Gates halt for the user. Run `check` before every unit of work.")
    return 0


def cmd_log(args, state):
    if state is None:
        print("Not engaged — nothing to log against.", file=sys.stderr)
        return 1
    unit = _arg_after(args, "--unit")
    outcome = _arg_after(args, "--outcome")
    if not unit:
        print('log requires --unit "..."', file=sys.stderr)
        return 1
    if outcome not in OUTCOMES:
        print(f"log requires --outcome <{'|'.join(OUTCOMES)}>", file=sys.stderr)
        return 1
    now = _iso_now()
    u = read_usage()
    state["log"].append({"at": now, "unit": unit, "outcome": outcome, "note": _arg_after(args, "--note")})
    c = read_context()
    if u["ok"]:
        state["last_check"] = {"at": now, "five_hour_pct": _js_round(u["pct"]), "resets_at": u["resets_at"],
                               "context_tokens": c["tokens"] if c["ok"] else None}
    write_state(state)
    commit_state(f"{outcome} — {unit}")
    print(f"Logged: {unit} ({outcome})" + (f" · {usage_line(u)}" if u["ok"] else "") +
          (f" · context {k_tok(c['tokens'])}" if c["ok"] else ""))
    return 0


def cmd_disengage(args, state):
    reason = _arg_after(args, "--reason")
    if reason not in REASONS:
        print(f"disengage requires --reason <{'|'.join(REASONS)}>", file=sys.stderr)
        return 1
    now = _iso_now()
    u = read_usage()
    c = read_context()
    base = state if state is not None else {"threshold_pct": DEFAULT_THRESHOLD, "stop_at_gates": True, "log": []}
    write_state({
        **base,
        "status": "paused",
        "paused": {
            "at": now, "reason": reason,
            "five_hour_pct": _js_round(u["pct"]) if u["ok"] else None,
            "resets_at": u["resets_at"] if u["ok"] else None,
            "context_tokens": c["tokens"] if c["ok"] else None,
            "next_action": _arg_after(args, "--next"),
        },
    })
    commit_state(f"paused ({reason})")
    done = len([e for e in (base.get("log") or []) if e.get("outcome") == "done"])
    print(f"Autopilot PAUSED — {reason}")
    print(f"  {done} unit(s) completed this run." + (f" {usage_line(u)}" if u["ok"] else ""))
    if u["ok"] and u["resets_at"] and reason == "usage-threshold":
        print(f"  The 5-hour window resets {clock(u['resets_at'])} (in {human_in(u['resets_at'] - _now_s())}).")
    if reason == "context-threshold":
        print(f"  Context {k_tok(c['tokens']) + ' tokens' if c['ok'] else 'size'} — a fresh session is the fix: /clear, then /rebuild.")
    print("  Now run: python3 scripts/pause_check.py — and resolve what it flags.")
    return 0


def cmd_status(args, state):
    # Context is printed whether or not a run exists: an attended session uses this line to
    # decide when to end itself (SKILL.md, Context hygiene).
    c = read_context()
    ctx_line = (f"  context {k_tok(c['tokens'])} tokens · limit {k_tok(context_limit_of(args, state))}"
                if c["ok"] else f"  context unknown — {c['reason']}")
    if state is None:
        print("Autopilot: off (no plan/autopilot.yaml).")
        print(ctx_line)
        return 0
    print(f"Autopilot: {_u(state['status'])}")
    if state["engaged_phase"]:
        print(f"  engaged at: {state['engaged_phase']} ({_u(state['engaged_at'])})")
    print(f"  threshold: {_js_str(state['threshold_pct'])}% · gates halt: {'true' if state['stop_at_gates'] else 'false'}")
    if state["paused"] is not None:
        paused = state["paused"]
        print(f"  paused {_u(paused.get('at'))} — {_u(paused.get('reason'))}")
        if paused.get("next_action"):
            print(f"  next_action (hint only): {paused['next_action']}")
    if state["log"]:
        print(f"  {len(state['log'])} unit(s) logged:")
        for e in state["log"][-10:]:
            print(f"    {_u(e.get('outcome')).ljust(7)} {_u(e.get('unit'))}")
    u = read_usage()
    print(f"  {usage_line(u)}" if u["ok"] else f"  usage unknown — {u['reason'].split(chr(10))[0]}")
    print(ctx_line)
    return 0


COMMANDS = {
    "check": cmd_check, "preflight": cmd_preflight, "engage": cmd_engage,
    "log": cmd_log, "disengage": cmd_disengage, "status": cmd_status,
}


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            # newline="\n": Node's console.log writes a bare LF on Windows too, and callers
            # (a statusline, a lane brief's grep) match on lines.
            s.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        except Exception:
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    state = read_state()
    cmd = args[0] if args and args[0] else "status"
    handler = COMMANDS.get(cmd)
    if handler is None:
        print("Usage: autopilot.py preflight | check | engage | log | disengage | status", file=sys.stderr)
        return 1
    return handler(args, state)


if __name__ == "__main__":
    sys.exit(main())
