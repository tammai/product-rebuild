#!/usr/bin/env python3
"""autopilot_guard.py — PreToolUse hook: stop an ENGAGED autopilot run once the 5-hour
rate-limit window crosses its threshold.

Why a hook rather than an instruction: "pause at 80%" written in a reference file is a
rule the model applies to itself while mid-slice and convinced the current unit is nearly
done. This one is not negotiable — the write simply fails, and the block message says what
to do instead. It is the difference between a budget and a limit.

It blocks exactly ONCE. `disengage` is a Bash call, which this matcher never sees, and it
flips status to `paused` — after which this guard fails open and the model can freely write
the drafts, commits and pause report the stop procedure requires.

Exit 0 = allow. Exit 2 = block (stderr is fed back to the model).

Fail-open up to the point where an engaged run is established, and closed after it. Every
early exit below — no payload, no target path, not in a workbench, no autopilot state,
state not `engaged` — returns 0, because none of those is an autopilot write and the guard
must never break an unrelated edit. Once `status: engaged` is confirmed, the calculus
inverts: an unverifiable window is not a low one, and the run has already declared itself
unattended. Allowing writes there would mean the threshold silently stops existing exactly
when the status line breaks — which is the one failure this guard is here to survive.

The escape from a run left `engaged` by a session that died is one command, named in the
block message: `autopilot.py disengage`.
"""

import json
import math
import os
import re
import sys
import time

from hooklib import locate, get, js_number, read_text, truthy, utf8_stdio

# Deliberately far looser than the 15 minutes `autopilot.py check` allows, because the two
# run at different distances from a status-line render.
#
# Measured: the status line re-renders at tool-call BOUNDARIES, not during a call. Inside one
# 100-second foreground call the snapshot updated at the start, then went 95 seconds without a
# write, then updated as the call ended. `check` runs at unit boundaries, moments after a
# render, so 15 minutes there is generous. This hook can fire in the middle of a long one — a
# subagent writing its findings twenty minutes into a slice build — where the snapshot is
# legitimately old and nothing is wrong.
#
# So: 45 minutes. Long enough that no realistic single tool call trips it, short enough that a
# status line which has genuinely stopped is caught while the run is still worth stopping.
MAX_SNAPSHOT_AGE_S = 2700

_MISSING = object()


def _round(x):
    # Math.round rounds halves up; Python's round() rounds them to even.
    return int(math.floor(x + 0.5))


def _clock(epoch_s):
    """The reset time as toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) printed it:
    12-hour with AM/PM under an English (or unset) locale, 24-hour elsewhere. An approximation
    of the system locale, not ICU: only the hint after "resets at" depends on it."""
    lang = os.environ.get("LC_ALL") or os.environ.get("LC_TIME") or os.environ.get("LANG") or ""
    local = time.localtime(epoch_s)
    if lang in ("", "C", "POSIX") or lang.startswith("en_US") or lang.startswith("en-US"):
        return time.strftime("%I:%M %p", local)
    return time.strftime("%H:%M", local)


def main(argv=None):
    utf8_stdio()
    payload, _abs, root = locate()

    state_path = os.path.join(root, "plan", "autopilot.yaml")
    if not os.path.exists(state_path):
        return 0  # autopilot has never run here

    try:
        state = read_text(state_path)
    except Exception:
        return 0
    if not re.search(r"^status: engaged$", state, re.M):
        return 0  # paused or off — nothing to enforce

    m = re.search(r"^threshold_pct: ([0-9]+)$", state, re.M)
    threshold = int(m.group(1)) if m else 0
    threshold = threshold or 80

    # --- from here the run is engaged: fail CLOSED ------------------------------------------

    snapshot_path = os.environ.get("REBUILD_RATE_LIMITS") or os.path.join(os.path.expanduser("~"), ".claude", ".rate-limits.json")

    # A subagent gets a different instruction, because the remedy is not its to run. A miner or
    # spec-writer that disengaged the parent's run would be ending a session it cannot see —
    # and `disengage` records a `next_action` only the orchestrator knows. So: stop, report up.
    as_subagent = bool(get(payload, "agent_id") or get(payload, "agent_type"))

    def remedy(reason, next_):
        if as_subagent:
            return (f"Stop this unit now and return to your orchestrator, reporting: \"{reason}\".\n"
                    f"Do NOT run autopilot.py yourself, and do not retry the write — ending the run is the\n"
                    f"orchestrator's call, and it is the only one that knows what comes next.")
        return (f"Stop the run now — do not finish the current unit first. In order:\n"
                f"  1. python3 scripts/autopilot.py disengage --reason {next_} --next \"<what comes next>\"\n"
                f"     (this unblocks writing, so drafts and commits work again)\n"
                f"  2. Save any in-flight work to disk, commit, and push the workbench and every repo in repos.yaml\n"
                f"  3. python3 scripts/pause_check.py — and resolve what it flags\n"
                f"  4. Report the pause to the user and ask whether to continue after the reset or stop here.")

    def block_unverifiable(why):
        print(
            f"Blocked: autopilot is engaged, but the 5-hour usage window cannot be verified — {why}\n"
            f"An unverifiable window is not a low one, so the run stops rather than continuing blind.\n"
            f"If the status line has stopped writing {snapshot_path}, that is the cause; if this run\n"
            f"was left engaged by an earlier session, disengaging clears it.\n"
            + remedy(f"autopilot cannot verify the usage window — {why}", "error"),
            file=sys.stderr,
        )
        sys.exit(2)

    if not os.path.exists(snapshot_path):
        block_unverifiable(f"no snapshot at {snapshot_path}.")

    try:
        with open(snapshot_path, "rb") as f:
            snap = json.loads(f.read().decode("utf-8", errors="replace"))
    except Exception:
        block_unverifiable(f"the snapshot at {snapshot_path} is unreadable.")

    at = get(snap, "at")
    age = math.floor(time.time()) - js_number(at if truthy(at) else 0)
    if not math.isfinite(age):
        block_unverifiable("the snapshot carries no readable timestamp.")
    if age > MAX_SNAPSHOT_AGE_S:
        block_unverifiable(f"the snapshot is {_round(age / 60)}m old (limit {MAX_SNAPSHOT_AGE_S // 60}m).")

    five = get(snap, "five_hour")
    used = five.get("used_percentage", _MISSING) if isinstance(five, dict) else _MISSING
    pct = float("nan") if used is _MISSING else js_number(used)
    if not math.isfinite(pct):
        block_unverifiable("the snapshot has no five_hour.used_percentage.")
    if pct < threshold:
        return 0

    resets_at = js_number(five.get("resets_at")) if isinstance(five, dict) else 0.0
    if not math.isfinite(resets_at):
        resets_at = 0.0  # NaN is `|| 0` in the original; an infinite time has no clock to print
    resets = f" The window resets at {_clock(resets_at)}." if resets_at else ""

    print(
        f"Blocked: autopilot is engaged and the 5-hour usage window is at {_round(pct)}%, "
        f"at or over its {threshold}% threshold.{resets}\n"
        + remedy(f"the 5-hour usage window is at {_round(pct)}%, over the {threshold}% threshold", "usage-threshold"),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
