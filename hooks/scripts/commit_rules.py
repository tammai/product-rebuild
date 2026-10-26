#!/usr/bin/env python3
"""commit_rules.py — the Conventional-Commit subject rule, written once, usable two ways:
  from commit_rules import subject_problem     commit_gates.py, the Claude-side check
  python3 commit_rules.py <msg-file>            a git `commit-msg` hook

WHY ONE FILE. The rule has to hold for a commit made through Claude (commit_gates.py sees
the `git commit -m` before it runs) and for one made by hand in a terminal (only a git hook
sees that). Two copies of a regex and a type list drift: one accepts `wip:` and the other does
not, and a lane learns which to trust. So scaffold-repo vendors THIS file into each code repo
as `scripts/commit-msg.py`, hashes it in the repo's scaffold lock, and refuses to overwrite a
locally edited copy — one source, and drift is visible instead of silent.

It imports nothing from this plugin, because the vendored copy runs in a repo that has none of
it. Keep it that way: standard library only, and nothing that reads a sibling file.

FAILS OPEN when it cannot read a subject (no file argument, unreadable file, an empty message):
the commit-msg hook exists to catch a bad subject, not to turn a git problem into a blocked
commit. Exit 2 rejects.
"""

import re
import sys

TYPES = ["feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert"]
# `.` in the JS original refused \r,   and   as well as \n; spelled out so a subject
# that is only a line separator after the colon is judged the same way.
CONVENTIONAL = re.compile(r"^(" + "|".join(TYPES) + r")(\([^()]+\))?!?: [^\n\r  ]+")
MAX_SUBJECT = 100

# What String.prototype.trim strips: not Python's set (which adds \x1c-\x1f and \x85 and lacks
# the byte-order mark), so a subject is trimmed the way the JS-era hook trimmed it.
_JS_WS = "\t\n\x0b\x0c\r   " + "".join(chr(c) for c in range(0x2000, 0x200B)) + "    　﻿"


def _js_length(s):
    # The limit is stated in the message as "chars"; the original counted UTF-16 code units.
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def subject_problem(subject):
    """The message to show for a subject that breaks the rule, or None when it is fine. Git's own
    generated subjects and rebase markers are not ours to reformat."""
    if not subject:
        return None
    if re.search(r"^(Merge|Revert)\b", subject, re.A) or re.search(r"^(fixup|squash)!", subject):
        return None
    if not CONVENTIONAL.search(subject):
        return f'Error: commit message is not a Conventional Commit. Use "<type>(<scope>): <subject>" — type one of: {", ".join(TYPES)}. Append ! before the colon for a breaking change. Got: "{subject}"'
    length = _js_length(subject)
    if length > MAX_SUBJECT:
        return f'Error: commit subject is {length} chars (max {MAX_SUBJECT}). Move the detail into a body: git commit -m "<subject>" -m "<body>".'
    return None


def subject_from_file(path):
    """A git commit-msg hook's file: the first line that is neither a comment nor blank. The file
    still carries git's comment template and any scissors line at this point."""
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    for line in re.sub(r"\r\n?", "\n", text).split("\n"):
        if line.startswith("#") or line.strip(_JS_WS) == "":
            continue
        return line.strip(_JS_WS)
    return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        except Exception:
            pass
    problem = None
    try:
        problem = subject_problem(subject_from_file(argv[0])) if argv and argv[0] else None
    except Exception:
        return 0  # unreadable input → can't judge → never block on guard failure
    if problem:
        print(problem, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
