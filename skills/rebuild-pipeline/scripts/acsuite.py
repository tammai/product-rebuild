#!/usr/bin/env python3
"""acsuite.py — read the AC suite's own JUnit output. Imported by parity.py,
slice_review.py, equiv.py and lanes_check.py; runs nothing on its own.

The rule this exists to serve is g5-build.md's: an artifact a human reads afterwards must
name only what actually RAN. A transcribed pass rate is exactly the banner that survives
after the run that produced it is forgotten, so both consumers read the XML rather than a
summary — and anything unreadable is reported as unreadable, never counted as zero failures.

Deliberately not an XML parser. JUnit's shape is fixed enough that counting <testcase>
elements and the ones carrying a <failure>/<error>/<skipped> child is reliable, and a real
parser would reject a half-written file that this one still counts what it can of. (The
Node original shipped no dependencies; the port keeps the hand scan because it is the
behaviour the reports were written against, not because Python lacks a parser.)

Ported from acsuite.mjs. Every JS-versus-Python difference that could change a report is
handled where it occurs and named in a comment: `\\s` and `.trim()` (JS counts U+FEFF and
the Unicode spaces, Python's str.strip counts the C0 separators instead), `Math.round`
(ties go up, Python's round() goes to even), `String.slice` (UTF-16 units),
`localeCompare` (ICU collation), `readdirSync` (sorted by libuv) and `path.join`
(normalising). Dict keys are the JS property names verbatim (`caseName`, `stillFailing`,
`rerunPasses`, ...) because they are data that consumers index by name.
"""

import errno
import json
import math
import os
import re
import unicodedata
from datetime import datetime

# --- JS-compatible text helpers --------------------------------------------------------------

# What JS `\s` and `String.prototype.trim` treat as white space: Python's `\s` / str.strip()
# differ at both ends (JS includes U+FEFF, excludes U+001C..U+001F). A skip reason or a unlock
# reason that began with a BOM would otherwise be cut differently by the two ports.
JS_WS = " \t\n\v\f\r           " \
        "      　﻿"
_WS = "[" + JS_WS.replace("\\", "\\\\") + "]"


def js_trim(s):
    return s.strip(JS_WS)


def js_slice(s, start, end=None):
    """String.prototype.slice, which counts UTF-16 code units, not code points: an emoji at the
    cut makes the two disagree by one character. Lone surrogates survive, as in JS."""
    b = s.encode("utf-16-le", "surrogatepass")
    units = len(b) // 2
    e = units if end is None else min(end, units)
    return b[start * 2:e * 2].decode("utf-16-le", "surrogatepass")


def js_len(s):
    """String.prototype.length: UTF-16 code units. Longest-first id sorts compare these."""
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def js_round(x):
    """Math.round: halves go up (12.5 -> 13, -0.5 -> -0). Python's round() is banker's."""
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


def js_num(x):
    """How JS prints a number in a template literal: 10, not 10.0."""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def js_error_text(e):
    """Node's e.message for a failed read ("EISDIR: illegal operation on a directory, read"),
    which is what the `unreadable` reason carries into a report. Python's strerror words differ
    ("Is a directory"), so the common codes are spelled the libuv way."""
    code = errno.errorcode.get(getattr(e, "errno", None) or 0)
    if not code:
        return str(e)
    words = {
        "EISDIR": "illegal operation on a directory", "EACCES": "permission denied",
        "ENOENT": "no such file or directory", "EPERM": "operation not permitted",
    }.get(code, (e.strerror or "").lower())
    syscall = "read" if code == "EISDIR" else "open"
    tail = f" '{e.filename}'" if syscall == "open" and getattr(e, "filename", None) else ""
    return f"{code}: {words}, {syscall}{tail}"


def _alias(k):
    """caseName <-> case_name. The JS property names are the canonical keys here; the snake_case
    spelling is accepted on read because modules ported alongside this one (sequence.py,
    basis.py) use snake_case result keys and a caller should not have to remember which this one
    is."""
    if not isinstance(k, str):
        return k
    snake = re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), k)
    if snake != k:
        return snake
    return re.sub(r"_([a-z])", lambda m: m.group(1).upper(), k)


class Rec(dict):
    """A result dict readable as `r["caseName"]`, `r["case_name"]`, `r.caseName` or `r.case_name`.
    Writes and iteration use the canonical (JS) key only, so `json.dumps(rec)` gives the keys the
    JS did."""

    def __missing__(self, k):
        a = _alias(k)
        if a != k and dict.__contains__(self, a):
            return dict.__getitem__(self, a)
        raise KeyError(k)

    def __contains__(self, k):
        return dict.__contains__(self, k) or dict.__contains__(self, _alias(k))

    def get(self, k, default=None):
        try:
            return self[k]
        except KeyError:
            return default

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


def js_truthy(x):
    """JS truthiness, for values that came out of hand-edited JSON: `{}` and `[]` are truthy in
    JS and falsy in Python, and a run record is exactly the kind of file someone edits."""
    if x is None or x is False or x == "" or (isinstance(x, (int, float)) and not isinstance(x, bool) and (x == 0 or x != x)):
        return False
    return True


def _repos(m):
    r = m.get("repos")
    return r if isinstance(r, dict) else {}


def js_prop(o, k):
    """`o.k` in JS: undefined (None) instead of an error when o is not an object."""
    return o.get(k) if isinstance(o, dict) else None


# Same ordering ICU's localeCompare gives for the characters ids and file names contain:
# punctuation, then digits, then letters case-insensitively, with lower before upper only as
# the last tiebreak. Python's default string order puts "B" before "a", which re-sorts the
# traces list. The table was read off `Array.sort(localeCompare)` on all printable ASCII.
_PUNCT_ORDER = " _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"


def locale_compare_key(s):
    prim, sec, ter = [], [], []
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.combining(ch):
            if sec:
                sec[-1] += ch
            continue
        low = ch.lower() if len(ch.lower()) == 1 else ch
        if ch in _PUNCT_ORDER:
            p = _PUNCT_ORDER.index(ch)
        elif "0" <= ch <= "9":
            p = 100 + int(ch)
        elif "a" <= low <= "z":
            p = 200 + ord(low) - 97
        else:
            p = 1000 + ord(low)
        prim.append(p)
        sec.append("")
        ter.append(1 if ch != low else 0)
    return (prim, sec, ter)


def _read_text(p):
    """CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the
    working copy is CRLF, and a pattern with a literal `\\n` (`^slices:\\n`, `^---\\n`) silently
    matches nothing — read as "no such block" rather than an error. Same helper in every script
    that parses text; copied, not imported, because each is vendored and must run alone. See
    playbook.py's read_text for the incident. `errors="replace"` because Node's utf8 decoding
    never fails: a file with a stray byte is still counted, as it always was."""
    with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


def _join(*parts):
    """path.join normalises ("." + "parity" is "parity/x", not "./parity/x"); os.path.join does
    not, and the printed paths in a report would change."""
    return os.path.normpath(os.path.join(*parts))


def _listdir(d):
    """readdirSync is alphasort-ed by libuv; os.listdir is in directory order. Several reports
    list what this returns, so the order is part of the output."""
    return sorted(os.listdir(d))


def local_date(d=None):
    """Today on the LOCAL calendar, as YYYY-MM-DD — the date every dated file in parity/ is named by.

    It used to be `new Date().toISOString().slice(0, 10)`, which is the UTC date, while the lanes
    name their JUnit files by the local one. East of UTC those disagree every local morning: at
    04:00 in UTC+7 a parity run overwrote the previous day's committed report, and slice-review
    read the previous slice's JUnit as "today". A date that names or looks up a file uses this;
    log timestamps stay UTC instants, because they name nothing.

    datetime.now() is local time and honours TZ (Python calls tzset at start-up), which is what
    eval/dates_and_reruns.py relies on to force the local and UTC dates apart. Takes a
    datetime/date (or epoch seconds) for tests; an aware datetime is converted to local, a
    naive one is taken as already local, as a JS Date's getFullYear() would give.
    """
    if d is None:
        d = datetime.now()
    elif isinstance(d, (int, float)):
        d = datetime.fromtimestamp(d)
    elif getattr(d, "tzinfo", None) is not None:
        d = d.astimezone()
    return f"{d.year}-{d.month:02d}-{d.day:02d}"


def ac_junit_path(date, root="."):
    return _join(root, "parity", f"{date}-ac.xml")


def ac_rerun_path(date, root="."):
    """The rerun of the joint run's failures (g5-build.md, "Test cadence within a slice"), and the
    run records both runs leave beside their JUnit. `ac_junit_files` below matches `-ac.xml$` only,
    so a rerun file is never mistaken for a joint run — keep it that way."""
    return _join(root, "parity", f"{date}-ac-rerun.xml")


def run_meta_path(date, opts=None, root=".", rerun=False):
    """`opts` carries `{ "rerun": True }` the way the JS options object did; `rerun=` is accepted
    as a keyword too."""
    if opts and opts.get("rerun"):
        rerun = True
    return _join(root, "parity", f"{date}-ac{'-rerun' if rerun else ''}.meta.json")


def read_run_meta(path):
    """Read a run record: `{ started, repos: { <name>: { path, sha, dirty } } }`, written by
    `lanes_check.py stamp` right before the run starts. JUnit has no standard field for the
    commit it ran against, which is the one fact needed to say what a rerun pass means.
    Returns None when absent and { unreadable } when present but not usable — never a guess.

    json.loads accepts NaN/Infinity, which JSON.parse rejects; refused here so a hand-edited
    record is "unreadable" in both ports. The message text is Python's, not V8's.
    """
    if not os.path.exists(path):
        return None

    def _no_const(c):
        raise ValueError(f"Unexpected token {c} in JSON")

    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            m = json.loads(f.read(), parse_constant=_no_const)
        # JS: `!m || typeof m.repos !== "object"` — null and arrays count as objects there.
        if not (isinstance(m, dict) and "repos" in m and (m["repos"] is None or isinstance(m["repos"], (dict, list)))):
            return {"unreadable": "no `repos` object"}
        return m
    except OSError as e:
        return {"unreadable": js_error_text(e)}
    except json.JSONDecodeError as e:
        # V8 says "Unexpected end of JSON input" for a record cut off mid-write — the one failure
        # a crashed `stamp` actually produces. Other messages keep Python's wording.
        cut = e.pos >= len(e.doc) and not e.msg.startswith(("Extra data", "Unterminated"))
        return {"unreadable": "Unexpected end of JSON input" if cut else str(e)}
    except ValueError as e:
        return {"unreadable": str(e)}


def count_with_rerun(joint, rerun=None, joint_meta=None, rerun_meta=None):
    """The joint run plus its rerun, counted once — the ONE place a pass rate is decided, so
    parity.py and slice_review.py cannot state two different numbers for the same slice.

    A criterion counts as PASS if it passed in the joint run, or failed there and passed in the
    rerun. But a green rerun means one of two different things, and they are never reported as one:

      - "flaky"        the same commits ran both times. The test failed and then passed on the same
                       code; that is a finding about the test, not a pass to be banked quietly.
      - "code-changed" commits landed between the runs. Only the failed specs re-ran against the new
                       code, so nothing checked what the fix did to the tests that passed earlier.
      - "unverified"   a run record is missing or unreadable, or a tree was dirty when it was
                       stamped, so which code ran cannot be said. Never silently a PASS.

    Without a rerun this returns the joint run's own numbers, so callers need no second path.
    """
    if not joint or joint.get("unreadable"):
        return None
    base = Rec({
        "total": joint["total"], "passed": joint["passed"], "failed": joint["failed"],
        "skipped": joint["skipped"], "stillFailing": [c["name"] for c in joint["failures"]],
        "rerunPasses": [], "notRerun": [], "extra": [], "changed": [], "rerun": None,
        "cases": joint["cases"],
    })
    if not rerun:
        return base
    if rerun.get("unreadable"):
        return Rec({**base, "rerun": {"unreadable": rerun["unreadable"]}})

    # Sets in the JS; dict.fromkeys keeps their insertion order, which the report lists in.
    failed_names = list(dict.fromkeys(c["name"] for c in joint["failures"]))
    rerun_state = {c["name"]: c["state"] for c in rerun["cases"]}

    # Which code each run saw. Any difference, dirt, or missing record decides the label for
    # every rerun pass at once: the two runs are one comparison, not one per test.
    label = "flaky"
    changed = []

    def usable(m):
        return js_truthy(m) and not m.get("unreadable")

    if not usable(joint_meta) or not usable(rerun_meta):
        label = "unverified"
    else:
        jr, rr = _repos(joint_meta), _repos(rerun_meta)
        for n in dict.fromkeys([*jr.keys(), *rr.keys()]):
            a, b = jr.get(n), rr.get(n)
            if not js_truthy(a) or not js_truthy(b) or js_truthy(js_prop(a, "dirty")) or js_truthy(js_prop(b, "dirty")):
                label = "unverified"
                continue
            if js_prop(a, "sha") != js_prop(b, "sha"):
                changed.append({"repo": n, "path": js_prop(b, "path") if js_truthy(js_prop(b, "path")) else js_prop(a, "path"),
                                "from": js_prop(a, "sha"), "to": js_prop(b, "sha")})
        if label != "unverified" and changed:
            label = "code-changed"

    rerun_passes, still_failing, not_rerun = [], [], []
    for name in failed_names:
        st = rerun_state.get(name)
        if st is None:
            not_rerun.append(name)
        elif st == "passed":
            rerun_passes.append({"name": name, "label": label})
        else:
            still_failing.append(name)
    extra = [c["name"] for c in rerun["cases"] if c["name"] not in failed_names]
    # The joint run's cases with rerun passes applied — what per-rule and per-feature tables group
    # on, so a rule is not reported red in one table and counted green in the headline above it.
    passed_on_rerun = {p["name"] for p in rerun_passes}
    cases = [Rec({**c, "state": "passed", "onRerun": label}) if c["name"] in passed_on_rerun else c
             for c in joint["cases"]]
    return Rec({
        **base,
        "passed": joint["passed"] + len(rerun_passes),
        "failed": joint["failed"] - len(rerun_passes),
        "stillFailing": [*still_failing, *not_rerun],
        "rerunPasses": rerun_passes, "notRerun": not_rerun, "extra": extra, "changed": changed,
        "label": label, "cases": cases,
        "rerun": {"path": rerun["path"], "total": rerun["total"]},
    })


RERUN_MEANING = {
    "flaky": "the same commits ran both times — each of these failed and then passed on the same "
             "code. That is a flaky acceptance test, and it goes into plan/progress.yaml `notes:` on the slice.",
    "code-changed": "commits landed between the runs, and only the failed specs re-ran against "
                    "them. The joint run's other passes predate those commits; nothing has checked what the fix "
                    "did to them.",
    "unverified": "a run record is missing or unreadable, or a tree was dirty when it was stamped, "
                  "so which code each run saw cannot be said. `python3 scripts/lanes_check.py stamp` before the "
                  "joint run (`stamp --rerun` before the rerun) records it.",
}


def describe_counted(c, joint_path):
    """The headline and the rerun block, as markdown lines — shared so both reports say the same
    thing in the same words. The joint run's own totals always appear; the rerun sits beside them
    and never replaces them."""
    rate = js_round((c["passed"] / c["total"]) * 100) if c["total"] else 0
    flaky = f", {len(c['rerunPasses'])} of them flaky" if c["rerunPasses"] and c.get("label") == "flaky" else ""
    skips = describe_skips(c["cases"])
    headline = f"{c['passed']}/{c['total']} passed ({rate}%){flaky}" \
        + (f", {c['failed']} failed" if c["failed"] else "") + (f", {c['skipped']} skipped" if c["skipped"] else "") \
        + (" — NOT GREEN (skips)" if skips["notGreen"] else "")
    lines = []
    if not c["rerun"]:
        return Rec({"headline": headline, "lines": skips["lines"], "notGreen": skips["notGreen"]})
    if c["rerun"].get("unreadable"):
        lines.append(f"- A rerun file exists but could not be read as JUnit ({c['rerun']['unreadable']}). "
                     "The joint run's numbers stand alone; no failure counts as re-run.")
        return Rec({"headline": headline, "lines": [*lines, *skips["lines"]], "notGreen": skips["notGreen"]})
    joint_passed = c["passed"] - len(c["rerunPasses"])
    lines.append(f"- **Rerun of the joint run's failures.** Joint run: {joint_passed}/{c['total']} passed "
                 f"(`{joint_path}`); rerun: {c['rerun']['total']} test(s) (`{c['rerun']['path']}`).")
    if c["rerunPasses"]:
        lines.append(f"  - **Passed on rerun — {c['label']}** ({len(c['rerunPasses'])}): {RERUN_MEANING[c['label']]}")
        for p in c["rerunPasses"]:
            lines.append(f"    - {p['name']}")
        if c["label"] == "code-changed":
            for ch in c["changed"]:
                lines.append(f"    - {ch['repo']}: `{js_slice(ch['from'], 0, 12)}..{js_slice(ch['to'], 0, 12)}`")
    if len(c["stillFailing"]) - len(c["notRerun"]) > 0:
        lines.append(f"  - Still failing after the rerun: {' · '.join(n for n in c['stillFailing'] if n not in c['notRerun'])}")
    if c["notRerun"]:
        lines.append(f"  - Failed in the joint run and not re-run: {' · '.join(c['notRerun'])}")
    if c["extra"]:
        lines.append(f"  - ⚠️ The rerun contains {len(c['extra'])} test(s) that did not fail in the joint run "
                     f"({', '.join(c['extra'][:3])}{', …' if len(c['extra']) > 3 else ''}). They change no count here; "
                     "a rerun re-runs only the failures.")
    return Rec({"headline": headline, "lines": [*lines, *skips["lines"]], "notGreen": skips["notGreen"]})


def _dated_files(root, suffix):
    d = _join(root, "parity")
    if not os.path.exists(d):
        return []
    out = []
    for f in _listdir(d):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-" + suffix + r"\.xml", f, re.ASCII)
        if m:
            out.append({"date": m.group(1), "path": _join(d, m.group(0))})
    # Newest first. Dates are unique per suffix, so the JS comparator's tie case never arises.
    return sorted(out, key=lambda x: x["date"], reverse=True)


def ac_junit_files(root="."):
    """Every AC JUnit file on disk, newest first, as { path, date }.

    parity.py reads TODAY's file only — its report is dated and must not borrow another day's
    numbers. A slice review is written at a slice boundary, which is rarely the same day the
    suite last ran, so it takes the newest and says how old it is. Two different correct answers
    to "which run", which is why this returns the list rather than picking.
    """
    return _dated_files(root, "ac")


def equiv_junit_path(date, root="."):
    return _join(root, "parity", f"{date}-equiv.xml")


def equiv_junit_files(root="."):
    """Every EQUIVALENCE JUnit file on disk, newest first — `parity/<date>-equiv.xml`, written by
    `equiv replay`.

    Same shape as ac_junit_files and read by the same read_ac_suite, because it is the same format
    answering a different question: the AC suite asks whether the rebuild does what the spec
    says, the equivalence suite asks whether it produces what the OLD system produced. Keeping
    one reader is what lets parity.py and slice_review.py treat them alike — a trace that
    regressed since the last boundary is found by exactly the code that finds a regressed AC.
    """
    return _dated_files(root, "equiv")


def read_equiv_traces(root="."):
    """Traces on disk, per feature — what was RECORDED, as opposed to what was replayed.

    The two counts have to be separate and both have to be reported. A trace that exists and was
    never replayed is not a pass and is not a failure; it is evidence nobody has checked, and it
    is invisible in the JUnit precisely because the JUnit only contains what ran. "8 recorded, 6
    replayed, 6 green" is the honest line; "6/6 green" over the same directory is not.
    """
    d = _join(root, "parity", "equiv")
    if not os.path.exists(d):
        return []
    out = []
    for feature in _listdir(d):
        fdir = _join(d, feature)
        if not os.path.isdir(fdir):
            continue
        for f in (x for x in _listdir(fdir) if x.endswith(".trace.yaml")):
            out.append({"feature": feature, "name": re.sub(r"\.trace\.yaml$", "", f), "path": _join(fdir, f)})
    return sorted(out, key=lambda t: locale_compare_key(t["feature"] + t["name"]))


# Why a case was skipped: the <skipped message="..."> attribute, else the element's text. Go's
# junit reporters, Jest and Playwright each use one or the other.
def _unescape_xml(t):
    t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
    # fromCharCode keeps the low 16 bits, so a code point above U+FFFF wraps rather than erroring.
    t = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1)) % 65536), t, flags=re.ASCII)
    return t.replace("&amp;", "&")


_SKIPPED = re.compile(r"<skipped\b([^>]*?)(/>|>([\s\S]*?)</skipped>)", re.ASCII)
_MESSAGE = re.compile(r'\bmessage="([^"]*)"', re.ASCII)


def _skip_reason(body):
    m = _SKIPPED.search(body)
    am = _MESSAGE.search(m.group(1)) if m else None
    attr = am.group(1) if am else None
    text = (attr or (m.group(3) if m else None) or "")
    text = js_trim(js_trim(re.sub(r"<!\[CDATA\[|\]\]>", "", text)).split("\n")[0])
    return js_slice(_unescape_xml(text), 0, 200) if text else "(no reason given)"


# SKIP_BOUND is 10%: the AC suite has one test per criterion, so a legitimate skip (a test for a
# platform this machine is not) is rare, and a broken environment skips whole packages at once.
# An env-var skip is never legitimate in the joint run, whatever the ratio: the criterion was not
# tested, and the fix is the run's environment, not the test.
#
# A joint run once reported 0 failures with 670 of 1209 tests skipped, because the integration
# database settings never reached the test processes. Each report already said "a skipped AC is
# not a passing one", and the run still read as green, because nothing said it was not.
# Green means no failures, no errors, skips within SKIP_BOUND, and no skip caused by an unset
# environment variable (the joint-run rule in g5-build.md).
SKIP_BOUND = 0.1
# `\s` is JS_WS and the flags are ASCII|IGNORECASE: JS `\b`/`\w` are ASCII, and `i` there never
# folds a non-ASCII letter onto [A-Z]. If you change one of these patterns, change the .mjs twin's.
_ENV_SKIP_SRC = (
    r"\b(env(ironment)?\s+var(iable)?s?|env\s+not\s+set)\b|process\.env\.|os\.Getenv|\$\{?[A-Z][A-Z0-9]*_[A-Z0-9_]+"
    r"|\bset\s+[A-Z][A-Z0-9]*_[A-Z0-9_]+\b"
    r"|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b[^.]*\b(not\s+set|unset|empty|missing|undefined|required)\b"
    r"|\b(not\s+set|unset|missing|requires?)\b[^.]*\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b"
)
ENV_SKIP = re.compile(_ENV_SKIP_SRC.replace(r"\s", _WS), re.ASCII | re.IGNORECASE)


def is_env_skip(reason):
    return bool(ENV_SKIP.search(reason or ""))


def describe_skips(cases):
    skipped = [c for c in (cases or []) if c["state"] == "skipped"]
    if not skipped:
        return Rec({"notGreen": False, "lines": []})
    ratio = len(skipped) / len(cases)
    env = [c for c in skipped if is_env_skip(c.get("reason"))]
    lines = []
    if ratio > SKIP_BOUND:
        lines.append(f"- ⚠️ **NOT GREEN: {len(skipped)} of {len(cases)} tests skipped ({js_round(ratio * 100)}%)**, "
                     f"above the {js_num(SKIP_BOUND * 100)}% bound. A run that skipped this much did not test what it reports on; "
                     "find the shared cause below and run again.")
    if env:
        lines.append(f"- ⚠️ **NOT GREEN: {len(env)} skipped because an environment variable was unset.** "
                     "Those criteria were not tested and none counts as passed. Fix the run's environment "
                     "(a `NAME=value` line in run_phases.py's phases.txt reaches every later phase) and run again.")
    by_reason = {}
    for c in skipped:
        by_reason[c["reason"]] = by_reason.get(c["reason"], 0) + 1
    top = sorted(by_reason.items(), key=lambda kv: -kv[1])  # stable, like Array.sort
    lines.append(f"- Skipped, by reason ({len(skipped)}):")
    for reason, n in top[:8]:
        lines.append(f"  - {n} × {reason}{' — unset environment variable' if is_env_skip(reason) else ''}")
    if len(top) > 8:
        lines.append(f"  - … and {len(top) - 8} more reason(s)")
    return Rec({"notGreen": ratio > SKIP_BOUND or len(env) > 0, "lines": lines})


def read_ac_suite(path):
    """Parse one JUnit file. Returns { unreadable } rather than throwing or zeroing."""
    if not os.path.exists(path):
        return None
    try:
        xml = _read_text(path)
    except OSError as e:
        return Rec({"unreadable": js_error_text(e)})
    # Split on the opening tag so each chunk is one test case plus whatever it contained.
    chunks = re.split(r"<testcase\b", xml, flags=re.ASCII)[1:]
    if not chunks:
        return Rec({"unreadable": "no <testcase> elements"})
    cases = []
    for chunk in chunks:
        # Everything up to this case's end — self-closing, or the matching </testcase>.
        end = chunk.find("</testcase>")
        body = re.split(r"<testcase\b", chunk, flags=re.ASCII)[0] if end == -1 else chunk[:end]

        def attr(n, body=body):
            m = re.search(r'\b' + n + r'="([^"]*)"', body, re.ASCII)
            return (m.group(1) if m else "") or ""

        classname, case_name = attr("classname"), attr("name")
        name = " › ".join(x for x in (classname, case_name) if x) or "(unnamed)"
        if re.search(r"<skipped\b", body, re.ASCII):
            state = "skipped"
        elif re.search(r"<(failure|error)\b", body, re.ASCII):
            state = "failed"
        else:
            state = "passed"
        case = Rec({"name": name, "classname": classname, "caseName": case_name, "state": state})
        if state == "skipped":
            case["reason"] = _skip_reason(body)
        cases.append(case)

    def count(st):
        return sum(1 for c in cases if c["state"] == st)

    return Rec({
        "path": path, "total": len(cases), "passed": count("passed"), "failed": count("failed"),
        "skipped": count("skipped"), "cases": cases, "failures": [c for c in cases if c["state"] == "failed"],
    })


def group_by_feature(cases, feature_ids):
    """Group cases by feature id, best-effort, and say how much did not group.

    Maestro is run as `maestro test parity/flows`, and flows live at
    parity/flows/<feature-id>/<criterion>.yaml — so the feature id is normally in the classname
    or the path-shaped test name. "Normally" is doing real work in that sentence, which is why
    `ungrouped` is returned and reported rather than dropped: a feature id that fails to match
    would otherwise silently vanish from a per-slice breakdown, and a missing row reads exactly
    like a feature with no tests.
    """
    # longest first: F-API-0011 before F-API-001. Stable, as Array.sort is.
    ids = sorted(feature_ids, key=lambda s: -js_len(s))
    by_feature = {}
    ungrouped = []
    for c in cases:
        hay = f"{c['classname']} {c['caseName']} {c['name']}"
        hit = next((i for i in ids if i in hay), None)
        if hit is None:
            ungrouped.append(c)
            continue
        g = by_feature.setdefault(hit, {"passed": 0, "failed": 0, "skipped": 0, "total": 0})
        g[c["state"]] += 1
        g["total"] += 1
    return Rec({"byFeature": by_feature, "ungrouped": ungrouped})


def compare_runs(prev, curr):
    """What changed between two runs, by test name.

    This is the cumulative-regression signal nothing in the pipeline had. Every per-slice deploy
    criterion asserts only that slice's own features, so "did S3 break S1" had no answer — the AC
    pass rate is a single number and a number that moves does not say which way or which test.
    Comparing by name against the previous run does, and both files are already on disk.

    Names that appear in only one run are reported as added/removed rather than as changes: a
    renamed flow is not a regression, and counting it as one is how a report gets ignored.
    """
    if not prev or prev.get("unreadable") or not curr or curr.get("unreadable"):
        return None
    before = {c["name"]: c["state"] for c in prev["cases"]}
    after = {c["name"]: c["state"] for c in curr["cases"]}
    regressed, recovered, added, removed = [], [], [], []
    for name, now in after.items():
        if name not in before:
            added.append(name)
            continue
        was = before[name]
        if was == "passed" and now != "passed":
            regressed.append({"name": name, "now": now})
        elif was != "passed" and now == "passed":
            recovered.append(name)
    for name in before:
        if name not in after:
            removed.append(name)
    return {"regressed": regressed, "recovered": recovered, "added": added, "removed": removed}


def group_by_rule(cases, rule_ids):
    """Group cases by Rule Card id, and say which rules no test named.

    The same best-effort join as group_by_feature, on a different key and for a different
    question. A feature answers "is this thing built"; a rule answers "does it behave the way
    the reference behaved" — which is the question parity could not previously ask, because
    coverage counts features and a feature can be fully built, marked covered, and subtly
    wrong: the total rounds before tax instead of after, the state machine allows a transition
    the reference forbade.

    The join works because g5-build.md step 1 requires the rule id in the test NAME: an AC
    carrying `rule_id: R-BILL-002` maps 1:1 to a test, and that test names the id. Nothing
    enforces it at runtime — JUnit carries names, not metadata — so `untested` is returned
    rather than inferred. A rule with no test and a rule whose test forgot to name it look
    identical here, and calling both "untested" is the honest reading: in both cases nothing
    on disk demonstrates the rule holds.

    `green` counts only rules where every test naming them passed. One failing test among four
    makes the rule red, because a rule is one behavior — there is no partial credit for a
    calculation that is right in three cases out of four.
    """
    rule_ids = list(rule_ids)
    ids = sorted(rule_ids, key=lambda s: -js_len(s))  # longest first: R-API-0011 before R-API-001
    by_rule = {}
    for c in cases:
        hay = f"{c['classname']} {c['caseName']} {c['name']}"
        for i in ids:
            if i not in hay:
                continue
            g = by_rule.setdefault(i, {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "cases": []})
            g[c["state"]] += 1
            g["total"] += 1
            g["cases"].append(c)
            break  # longest match wins; a test names one rule
    untested = [i for i in rule_ids if i not in by_rule]
    green = [i for i, g in by_rule.items() if g["total"] and g["passed"] == g["total"]]
    red = [i for i, g in by_rule.items() if g["failed"] > 0]
    # A rule whose only tests were skipped is neither green nor red — a skipped AC is not a
    # passing one, and reporting it as red would blame the rule for a suite that did not run.
    skipped_only = [i for i, g in by_rule.items() if g["total"] and not g["failed"] and g["passed"] == 0]
    return Rec({"byRule": by_rule, "untested": untested, "green": green, "red": red, "skippedOnly": skipped_only})


def read_rule_cards(root=".", parse_yaml=None):
    """Every Rule Card id on disk, with its domain and kind. Zero rules = lane R never ran, which
    is why parity.py renders no rules table at all rather than an empty one.

    Takes the YAML parser as an argument instead of importing it, as the JS did so this module
    stayed importable from anywhere. In Python that is the same call parity.py and
    slice_review.py already make: pass `yamlio.load`.
    """
    d = _join(root, "findings", "rules")
    if not os.path.exists(d) or not parse_yaml:
        return []
    out = []
    for f in (x for x in _listdir(d) if re.search(r"\.ya?ml$", x)):
        try:
            data = parse_yaml(_read_text(_join(d, f)))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        domain = re.sub(r"\.ya?ml$", "", f)
        for r in data:
            if isinstance(r, dict) and js_truthy(r.get("id")):
                out.append({"id": r["id"], "domain": domain, "kind": r.get("kind"),
                            "features": r.get("features") if js_truthy(r.get("features")) else []})
    return out
