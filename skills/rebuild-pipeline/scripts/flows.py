#!/usr/bin/env python3
"""flows.py — the logged-decision mechanism for AC flow assertions. Run from the workbench root.
Usage:
  python3 scripts/flows.py status
  python3 scripts/flows.py unlock --reason "..." [--by <name>]
  python3 scripts/flows.py relock [--by <name>]

Standard library only, and deliberately so: the PreToolUse guard imports nothing from here but
reads the same file, and a guard that needs an install step to work is a guard that fails open
on a fresh clone.

WHY THIS EXISTS

`parity/flows/` holds the acceptance-criteria suite, recorded against the LEGACY app before
each slice builds (g5-build.md step 0). That authorship direction is the only thing making it
a parity harness rather than a suite that agrees with whatever got built. It is not
hash-locked into a gate — flows are recorded per slice, and gate-locking them would mean a
formal reopen every slice, which is the bookkeeping-versus-decisions line plan/progress.yaml
already draws. So the substitute rule is:

  An assertion in a recorded flow changes only with a logged human decision.

Same register as a gate reopen: a human decides, the reason is written down. This script is
the log, and hooks/scripts/flows_guard.py is the teeth. The failure being prevented is
specific: an agent with a red build and a flow within reach will loosen the assertion, and
the result is indistinguishable from a build that got better.
"""

import os
import re
import sys
from datetime import datetime, timezone

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def _read_text(p):
    with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


FLOWS_DIR = "parity/flows"
UNLOCK_FILE = os.path.join(FLOWS_DIR, ".unlocked.yaml")
DECISION_LOG = os.path.join(FLOWS_DIR, "DECISIONS.md")

# What JS `\s` and `.trim()` count as white space. Python's differ at both ends (JS has U+FEFF,
# Python's str.strip has U+001C..U+001F), and this read parses a file a human may have
# edited, so "reason:" followed by a BOM must be cut where the Node original cut it.
# Copied from acsuite.py — this script must run alone; change both together.
_JS_WS = " \t\n\v\f\r\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008" \
         "\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_WS = "[" + _JS_WS + "]"
# JS `^`, `$` and `.` under the /m flag treat all four line terminators alike; Python's treat
# only \n. After the CRLF read above only U+2028/U+2029 could differ, which a hand-edited
# reason could contain.
_LT = "\n\r\u2028\u2029"
_BOL = "(?:(?<=[" + _LT + "])|\\A)"
_DOT = "[^" + _LT + "]"
_EOL = "(?=[" + _LT + "]|\\Z)"


def read_unlock(root="."):
    """Is the assertion rule currently suspended, and why? Read by the guard and by pause-check."""
    p = os.path.normpath(os.path.join(root, UNLOCK_FILE))
    if not os.path.exists(p):
        return None
    try:
        text = _read_text(p)
    except OSError:
        return None

    def get(k):
        m = re.search(_BOL + k + ":" + _WS + "*(" + _DOT + "*)" + _EOL, text)
        if not m:
            return None
        return re.sub(r'^"|"\Z', "", m.group(1).strip(_JS_WS))

    return {"reason": get("reason") or "(no reason recorded)", "at": get("at") or "(unknown)",
            "by": get("by") or "unknown"}


def _iso_now():
    """Date.prototype.toISOString: UTC, millisecond precision, trailing Z. Python's isoformat
    would give +00:00 and microseconds."""
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    cmd = (argv[0] if argv else "") or "status"

    def arg_after(flag):
        if flag in argv:
            i = argv.index(flag)
            return argv[i + 1] if i + 1 < len(argv) else None
        return None

    by = arg_after("--by") or os.environ.get("USER") or "unknown"
    now = _iso_now()

    def yaml_str(s):
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'

    def write(path, text, mode="w"):
        with open(path, mode, encoding="utf-8", newline="\n") as f:
            f.write(text)

    def log_decision(line):
        os.makedirs(FLOWS_DIR, exist_ok=True)
        if not os.path.exists(DECISION_LOG):
            write(DECISION_LOG, "# AC flow assertion decisions\n\n"
                  "Every suspension of the assertion rule, and every restoration of it, in order.\n"
                  "Written by `python3 scripts/flows.py unlock|relock`. Do not edit by hand — the point of the\n"
                  "log is that it records what happened, not what someone remembers happening.\n\n")
        write(DECISION_LOG, line, "a")

    if cmd == "status":
        u = read_unlock()
        if u:
            print(f"AC flow assertions: UNLOCKED since {u['at']} by {u['by']}\n  reason: {u['reason']}")
            print("\nRe-lock as soon as the change is made: python3 scripts/flows.py relock")
            print("Left unlocked, the guard is off and nothing notices an assertion being loosened.")
        else:
            print("AC flow assertions: protected. Editing a committed flow under parity/flows/ is blocked.")
            print('  To change one deliberately: python3 scripts/flows.py unlock --reason "..."')
        return 0

    if cmd == "unlock":
        reason = arg_after("--reason")
        if not reason:
            print('Unlocking requires --reason "..." — it is a formal, logged event, same as a gate reopen.', file=sys.stderr)
            print('Say which assertion is changing and why the old one was wrong. "tests failing" is not a reason;', file=sys.stderr)
            print("it is the situation the rule exists for.", file=sys.stderr)
            return 1
        os.makedirs(FLOWS_DIR, exist_ok=True)
        write(os.path.join(FLOWS_DIR, ".unlocked.yaml"),
              "# AC flow assertions are temporarily unprotected. Written by scripts/flows.py.\n"
              "# Re-lock with: python3 scripts/flows.py relock\n"
              f"at: {now}\n"
              f"by: {yaml_str(by)}\n"
              f"reason: {yaml_str(reason)}\n")
        log_decision(f"- **{now}** · unlocked by {by}\n  - {reason}\n")
        print(f"AC flow assertions unlocked. Logged to {DECISION_LOG}.")
        print("Make the change, then: python3 scripts/flows.py relock")
        print("pause-check will flag this workbench as unsafe to pause until you do.")
        return 0

    if cmd == "relock":
        u = read_unlock()
        if not u:
            print("Already protected — nothing to re-lock.")
            return 0
        os.remove(os.path.join(FLOWS_DIR, ".unlocked.yaml"))
        log_decision(f"- **{now}** · re-locked by {by} (was unlocked {u['at']})\n")
        print(f"AC flow assertions re-locked. Logged to {DECISION_LOG}.")
        return 0

    print('Usage: flows.py status | unlock --reason "..." [--by <name>] | relock [--by <name>]', file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
