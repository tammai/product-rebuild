#!/usr/bin/env python3
"""equiv.py — the equivalence lane: does the rebuild produce what the OLD system produced?
Run from the workbench root.
Usage:
  python3 scripts/equiv.py status
  python3 scripts/equiv.py record <feature-id>          # drive the LEGACY instance, write traces
  python3 scripts/equiv.py replay <feature-id>|--all    # replay against the REBUILD, write JUnit
  python3 scripts/equiv.py accept <trace> --reason "..." # log a decision about a red trace
  python3 scripts/equiv.py unlock --reason "..."  |  relock

Needs yamlio.py (and the vendored PyYAML under _vendor/). Unlike preflight.py this cannot run
before G0 finishes — traces are recorded per slice, deep into G5 — and trace files carry
nested request/response bodies that a fixed-subset regex parser would mangle silently. The
hook and gate.py stay dependency-free because neither needs to parse a trace: the guard
needs a path, and gate.py needs the JUnit and the decision log.

WHAT THIS IS FOR

`parity/flows/` is already a characterization harness — but only through Maestro, on the
accessibility layer, for a `client-only` mobile rebuild. A `fullstack` rebuild of your own
legacy web app had no equivalent: G6 said which features were covered and whether AC passed,
never whether `POST /invoices` returns the same totals the old system returned. This lane is
the same principle one layer down: a trace green against the old system and then green
against the rebuild is evidence of parity.

Maestro answers *does the UI do what the old UI did*. This answers *does the system produce
what the old system produced*. A `client-only` rebuild uses Maestro alone; a `fullstack`
own-code rebuild uses both; a third-party reference uses neither.

RECORDED BEFORE THE SLICE'S BACKEND LANE STARTS, AND THE ORDER IS THE WHOLE POINT

A trace recorded after the rebuild exists is derived from the rebuild. It asserts what was
built, says nothing about the reference, and every later replay agrees with the code by
construction — the same argument g5-build.md step 0 makes for Maestro flows, and the reason
that property cannot be recovered afterwards short of standing the old system back up.

WHY IT IS GATED ON own-code

Replaying recorded traffic against a product you do not operate is neither legal nor
practical, and under clean-room posture reading the reference's responses at all is the thing
the posture forbids. So the lane runs only where `sources.yaml` says `reference.kind:
own-code` and the E4 preflight says the reference actually runs. Everywhere else it refuses
and says which condition failed — never a silent no-op, because an empty equivalence column
and a skipped lane look identical in a report.

PORTING NOTES (Node original: equiv.mjs)

Everything below that looks over-careful is there because the report text, the trace files and
the JUnit this writes must be byte-identical to what the Node version wrote: traces are
committed evidence and a re-recorded or re-formatted trace shows up as a diff on every file.
The JS semantics reproduced on purpose are: Object.keys order (integer-like keys first),
JSON.stringify (compact, JS number formatting, `undefined` omitted), `String(undefined)`,
`Array.prototype.sort()` on strings (UTF-16 order) and `.some`/`.trim` on JS white space.
`fetch` becomes urllib; the differences that survive are listed at do_request.
"""

import gzip
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone

import yamlio
from acsuite import local_date, JS_WS, js_trim, js_prop
from acsuite import js_truthy as _js_truthy

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def _read_text(p):
    with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


def _join(*parts):
    """path.join normalises; os.path.join does not (see acsuite._join)."""
    return os.path.normpath(os.path.join(*parts))


def _write(path, text, mode="w"):
    """LF on every platform: a trace is evidence, and a CRLF rewrite on Windows would diff it."""
    with open(path, mode, encoding="utf-8", newline="\n") as f:
        f.write(text)


EQUIV_DIR = "parity/equiv"
UNLOCK_FILE = _join(EQUIV_DIR, ".unlocked.yaml")
DECISION_LOG = _join(EQUIV_DIR, "DECISIONS.md")
CONFIG_FILE = _join(EQUIV_DIR, "config.yaml")

_WS = "[" + JS_WS + "]"
# JS `^`, `$`, `.` under /m count \r, U+2028 and U+2029 as line ends; Python's count only \n.
_LT = "\n\r\u2028\u2029"
_BOL = "(?:(?<=[" + _LT + "])|\\A)"
_DOT = "[^" + _LT + "]"
_EOL = "(?=[" + _LT + "]|\\Z)"


# ---------------------------------------------------------------------------
# JS value semantics. Trace and request files are YAML and responses are JSON, and the diff
# below has to say the same thing the JS said about them: which of `null`, `undefined`, `1` and
# `1.0` differ, in what order keys are visited, and how a value is printed in the report.
# ---------------------------------------------------------------------------
class _Undefined:
    """`undefined`: a missing key or an index past the end. Distinct from None (`null`), because
    {"a": null} and {} are different bodies and the diff must say so."""

    def __repr__(self):
        return "undefined"

    def __bool__(self):
        return False


UNDEF = _Undefined()


def js_truthy(x):
    """JS truthiness, `undefined` included (acsuite's does not know that sentinel)."""
    return x is not UNDEF and _js_truthy(x)


def js_num_str(x):
    """Number.prototype.toString. Python's repr gives the same shortest digits but writes
    1e+16 where JS writes 10000000000000000 and 1e-05 where JS writes 0.00001."""
    if isinstance(x, int):
        if abs(x) < 2 ** 53:
            return str(x)
        x = float(x)
    if x != x:
        return "NaN"
    if x in (float("inf"), float("-inf")):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    r = repr(abs(x))
    mant, _, ex = r.partition("e")
    exp = int(ex) if ex else 0
    ip, _, fp = mant.partition(".")
    digits = ip + fp
    n = len(ip) + exp
    while digits.startswith("0") and len(digits) > 1:
        digits = digits[1:]
        n -= 1
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        es = ("+" if e >= 0 else "-") + str(abs(e))
        body = digits + "e" + es if k == 1 else digits[0] + "." + digits[1:] + "e" + es
    return sign + body


def js_str(x):
    """String(x) / a template-literal interpolation."""
    if x is UNDEF:
        return "undefined"
    if x is None:
        return "null"
    if x is True:
        return "true"
    if x is False:
        return "false"
    if isinstance(x, (int, float)):
        return js_num_str(x)
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return ",".join("" if e is None or e is UNDEF else js_str(e) for e in x)
    return "[object Object]"


def js_join(seq, sep):
    """Array.prototype.join: null and undefined become the empty string."""
    return sep.join("" if e is None or e is UNDEF else js_str(e) for e in seq)


def _is_index_key(k):
    return k == "0" or (len(k) > 0 and k[0] in "123456789" and k.isascii() and k.isdigit() and int(k) < 2 ** 32 - 1)


def js_items(d):
    """Object.entries order: integer-like keys ascending, then the rest in insertion order. A
    response body keyed by status code or id would otherwise be diffed (and truncated at 20
    differences) in a different order."""
    items = [(js_str(k), v) for k, v in d.items()]
    idx = sorted((kv for kv in items if _is_index_key(kv[0])), key=lambda kv: int(kv[0]))
    return idx + [kv for kv in items if not _is_index_key(kv[0])]


def _u16(s):
    """Sort key for JS's default string sort, which compares UTF-16 code units."""
    return s.encode("utf-16-be", "surrogatepass")


def _quote(s):
    out = json.dumps(s, ensure_ascii=False)
    return re.sub("[\ud800-\udfff]", lambda m: "\\u%04x" % ord(m.group(0)), out)


def js_stringify(v):
    """JSON.stringify(v) with no indent. Returns None for `undefined`, as JS does; a template
    literal then prints the word, which is why callers go through js_str(...)."""
    if v is UNDEF:
        return None
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return js_num_str(v) if v == v and v not in (float("inf"), float("-inf")) else "null"
    if isinstance(v, str):
        return _quote(v)
    if isinstance(v, list):
        return "[" + ",".join("null" if e is UNDEF else js_stringify(e) for e in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(_quote(k) + ":" + js_stringify(x) for k, x in js_items(v) if x is not UNDEF) + "}"
    return "null"


def _stringify_text(v):
    s = js_stringify(v)
    return "undefined" if s is None else s


def _jtype(v):
    if v is UNDEF:
        return "undefined"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _strict_eq(a, b):
    """a === b for the scalar types a YAML or JSON document holds: True == 1 in Python, not in JS."""
    if _jtype(a) != _jtype(b):
        return False
    if isinstance(a, int) and not isinstance(a, bool):
        # YAML integers are exact in Python and doubles in JS: 12345678901234567000 in a trace
        # must equal the 1.2345678901234567e19 a JSON response parses to.
        a = float(a) if abs(a) >= 2 ** 53 else a
    if isinstance(b, int) and not isinstance(b, bool):
        b = float(b) if abs(b) >= 2 ** 53 else b
    return a is b or a == b


def _uget(o, k):
    """`o?.[k]`: undefined, not an error, when o is missing or not an object."""
    return o.get(k, UNDEF) if isinstance(o, dict) else UNDEF


def _json_loads(text):
    """JSON.parse. Differences closed on purpose: NaN/Infinity are not JSON; integers beyond 2**53
    are doubles in JS and would otherwise compare exactly here."""
    def no_const(c):
        raise ValueError("Unexpected token " + c)

    def parse_int(s):
        v = int(s)
        return v if abs(v) < 2 ** 53 else float(s)

    return json.loads(text, parse_constant=no_const, parse_int=parse_int)


# ---------------------------------------------------------------------------
# Adapter interface — capture() / diff()
#
# An HTTP response is only half of what a request does. `POST /invoices` returning the same
# JSON while writing a different row is not equivalence, and it is exactly the class of
# difference a rebuild produces: the API was transcribed from the contract and the persistence
# was rewritten. So a trace can declare `tables:` and an adapter snapshots them.
#
# The interface is two functions and deliberately no more:
#
#   capture(tables, side)  -> { [table]: rows }   a snapshot, JSON-serialisable
#   diff(before, after, ignore) -> [ { path, legacy, rebuild } ]   empty means equivalent
#
# `side` is "legacy" or "rebuild" and is resolved to a connection by config.yaml, so an adapter
# never learns which system it is talking to beyond that word.
#
# ONE ADAPTER SHIPS: postgres. It covers OpenProject, most Rails/Django legacy and the Go
# target. Job-queue capture is deliberately absent until a real own-code rebuild shows which
# side effects the row diff misses — guessing at that interface now would mean designing
# against an imagined failure, and the adapter boundary exists precisely so the second one can
# be added without touching this file's command surface.
#
# Adapters are NOT a playbook concern. The playbook describes the target; the adapter is needed
# on the legacy side, which the playbook says nothing about.
# ---------------------------------------------------------------------------
class _PostgresAdapter:
    """Rows of the declared tables, via `psql`. Zero client libraries: the plugin ships none."""

    name = "postgres"

    def available(self, conn):
        if not js_truthy(conn):
            return "no connection string (see config.yaml)"
        try:
            r = subprocess.run(["psql", "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            if r.returncode != 0:
                raise OSError("psql --version failed")
        except OSError:
            return "`psql` is not on PATH"
        # Reachability is NOT checked here — that is capture()'s job, and doing it twice would
        # double every connection timeout on a system that is simply down.
        return None

    def capture(self, tables, conn):
        out = {}
        for t in tables:
            # `order by 1` makes the snapshot stable run to run: an unordered select is free to
            # return the same rows in a different order, which would diff as every row changed.
            sql = f"select coalesce(json_agg(row_to_json(t) order by 1), '[]'::json) from \"{js_str(t)}\" t"
            args = ["psql", js_str(conn), "-At", "-c", sql]
            # stderr is PIPED, not inherited: psql's own multi-line connection errors would
            # otherwise print before this script's message and bury the one piece of context that
            # matters — which table, on which side, during which command.
            try:
                r = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=60, text=True, encoding="utf-8", errors="replace")
                failure = None if r.returncode == 0 else (r.stderr or "Command failed: " + " ".join(args))
                raw = r.stdout
            except FileNotFoundError:
                failure = "spawnSync psql ENOENT"
            except subprocess.TimeoutExpired:
                failure = "spawnSync psql ETIMEDOUT"
            if failure is not None:
                why = next((ln for ln in failure.split("\n") if js_trim(ln)), "")
                raise Exception(f'psql failed reading table "{js_str(t)}": {js_trim(why)}')
            try:
                out[js_str(t)] = _json_loads(js_trim(raw) or "[]")
            except Exception:
                raise Exception(f'psql returned unparseable JSON for table "{js_str(t)}"')
        return out

    def diff(self, before, after, ignore):
        return diff_values(before, after, "$", ignore)


ADAPTERS = {"postgres": _PostgresAdapter()}


# ---------------------------------------------------------------------------
# Structural diff, with `ignore` declared per trace and never inferred.
#
# Fields the rebuild is ALLOWED to differ on — surrogate ids, timestamps, hashes, whatever the
# Gate 4 contract renamed — are listed in the trace's `ignore:`. Anything not listed is a
# failure. That direction matters: a differ that guessed at "probably a timestamp" would quietly
# absorb the one difference somebody needed to see, and the guess would be invisible in the
# report. Declaring them makes the list reviewable, and adding to it is a logged decision.
#
# Patterns: `$.a.b`, `$.items[*].id`, and `**.created_at` for a field at any depth. A bare name
# means the top-level field only — `id` ignoring every `id` everywhere is how an equivalence
# suite becomes decorative, so that spelling has to be asked for explicitly as `**.id`.
# ---------------------------------------------------------------------------
def _re_escape(s):
    """The JS escape `[.*+?^${}()|[\\]\\\\]` -> `\\$&`. Not re.escape: the second replace below
    matches the literal text `\\[\\*\\]`, which only this exact escaping produces."""
    return re.sub(r"[.*+?^${}()|\[\]\\]", lambda m: "\\" + m.group(0), s)


def _path_matches(path, pattern):
    if pattern.startswith("**."):
        p = "^\\$(\\.[^.]+|\\[[0-9*]+\\])*\\." + _re_escape(pattern[3:]) + "\\Z"
    else:
        base = pattern if pattern.startswith("$") else "$." + pattern
        p = "^" + _re_escape(base).replace("\\[\\*\\]", "\\[\\d+\\]") + "\\Z"
    try:
        return re.search(p, path, re.ASCII) is not None
    except re.error:
        return False


def _is_ignored(path, ignore):
    if not js_truthy(ignore):
        return False
    if not isinstance(ignore, list):
        raise TypeError("(ignore || []).some is not a function")
    return any(_path_matches(path, pat) for pat in ignore)


def diff_values(a, b, path, ignore, out=None):
    if out is None:
        out = []
    if _is_ignored(path, ignore):
        return out
    ta, tb = _jtype(a), _jtype(b)
    if ta != tb:
        out.append({"path": path, "legacy": a, "rebuild": b})
        return out
    if ta == "array":
        if len(a) != len(b):
            out.append({"path": f"{path}.length", "legacy": len(a), "rebuild": len(b)})
        for i in range(max(len(a), len(b))):
            diff_values(a[i] if i < len(a) else UNDEF, b[i] if i < len(b) else UNDEF, f"{path}[{i}]", ignore, out)
        return out
    if ta == "object":
        da, db = dict(js_items(a)), dict(js_items(b))
        # new Set([...keys(a), ...keys(b)]): a's order, then b's extras. Object.keys already
        # puts integer-like keys first within each, which js_items did.
        for k in dict.fromkeys([*da.keys(), *db.keys()]):
            diff_values(da.get(k, UNDEF), db.get(k, UNDEF), f"{path}.{k}", ignore, out)
        return out
    if not _strict_eq(a, b):
        out.append({"path": path, "legacy": a, "rebuild": b})
    return out


# ---------------------------------------------------------------------------
# Gating. Refuses loudly rather than no-opping: an empty equivalence column and a lane that
# never applied look identical in a report, and only one of them means anything.
# ---------------------------------------------------------------------------
def _read_sources():
    text = _read_text("sources.yaml") if os.path.exists("sources.yaml") else ""
    block = re.search(_BOL + r"reference:\n((?:(?:[ \t]+" + _DOT + r"*)?\n)*)", text)

    def get(k):
        m = re.search(_BOL + _WS + "+" + k + ":" + _WS + "*(" + _DOT + "*)" + _EOL, block.group(1)) if block else None
        if not m:
            return ""
        v = re.split(_WS + "+#", js_trim(m.group(1)))[0]
        return re.sub(r"^[\"']|[\"']\Z", "", v) or ""

    return {"kind": get("kind"), "name": get("name")}


def _gate_reasons():
    reasons = []
    kind = _read_sources()["kind"]
    if kind != "own-code":
        reasons.append(f"sources.yaml has reference.kind: {kind or '(empty)'} — this lane needs `own-code`. "
                       "Replaying recorded traffic against a product you do not operate is neither legal nor "
                       "practical, and under clean-room posture reading the reference's responses is the thing "
                       "the posture forbids. A third-party rebuild uses the AC suite and the parity report; "
                       "parity.py says the lane does not apply rather than showing an empty column.")
    if not os.path.exists("preflight.json"):
        reasons.append("no preflight.json — run `python3 scripts/preflight.py` (G0's last action). This lane "
                       "replays against the legacy system, so \"the reference runs\" has to be a checked fact, "
                       "not an assumption.")
    else:
        pf = None
        try:
            with open("preflight.json", "r", encoding="utf-8", errors="replace", newline="") as f:
                pf = _json_loads(f.read())
        except Exception:
            pass  # handled below
        if not js_truthy(pf):
            reasons.append("preflight.json is unreadable — re-run `python3 scripts/preflight.py`.")
        else:
            checks = js_prop(pf, "checks")
            instance = next((c for c in (checks if js_truthy(checks) and isinstance(checks, list) else [])
                             if js_prop(c, "id") == "instance"), None)
            status = js_prop(instance, "status")
            if status != "pass":
                detail = js_prop(instance, "detail")
                reasons.append("preflight says the reference does not run (`instance` check: "
                               f"{js_str(status) if js_truthy(status) else 'absent'}"
                               f"{' — ' + js_str(detail) if js_truthy(detail) else ''}). "
                               "Stand the legacy system up and re-run `python3 scripts/preflight.py`.")
    return reasons


def _require_gate(cmd):
    reasons = _gate_reasons()
    if not reasons:
        return
    print(f"equiv {cmd}: this workbench does not meet the equivalence lane's gating condition.\n", file=sys.stderr)
    for r in reasons:
        print(f"  - {r}\n", file=sys.stderr)
    print("Nothing was written.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Config + traces
# ---------------------------------------------------------------------------
def _read_config():
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        cfg = yamlio.load(_read_text(CONFIG_FILE))
        return cfg if js_truthy(cfg) else None
    except Exception:
        return None


# Connections come from ENV VAR NAMES in config.yaml, not from literals. The workbench is a git
# repo that gets pushed, and a DSN with a password in it is a credential in version control —
# this directory is committed on purpose, which makes it exactly the wrong place for one.
def _resolve_side(cfg, side):
    s = js_prop(cfg, side)
    s = s if js_truthy(s) and isinstance(s, dict) else {}

    def pick(literal_key, env_key):
        env_name = s.get(env_key)
        if js_truthy(env_name) and os.environ.get(js_str(env_name)):
            return os.environ[js_str(env_name)]
        if js_truthy(env_name):
            return None  # named but unset — the caller reports which variable
        v = s.get(literal_key)
        return v if js_truthy(v) else None

    return {
        "baseUrl": pick("base_url", "base_url_env"),
        "db": pick("database_url", "database_url_env"),
        "baseUrlEnv": s.get("base_url_env"), "dbEnv": s.get("database_url_env"),
    }


def _list_dir(d):
    # readdirSync is alphasort-ed by libuv; os.listdir is not.
    return sorted(os.listdir(d))


def _trace_files(feature_id):
    if feature_id:
        dirs = [_join(EQUIV_DIR, feature_id)]
    else:
        dirs = [d for d in (_join(EQUIV_DIR, x) for x in _list_dir(EQUIV_DIR)) if os.path.isdir(d)] \
            if os.path.exists(EQUIV_DIR) else []
    out = []
    for d in dirs:
        if not os.path.exists(d):
            continue
        for f in (x for x in _list_dir(d) if x.endswith(".trace.yaml")):
            out.append(_join(d, f))
    return sorted(out, key=_u16)


def _request_files(feature_id):
    d = _join(EQUIV_DIR, feature_id)
    if not os.path.exists(d):
        return []
    return sorted((_join(d, f) for f in _list_dir(d) if f.endswith(".request.yaml")), key=_u16)


def _parent_name(p):
    return os.path.basename(os.path.dirname(p))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """fetch(..., { redirect: "manual" }): a 3xx is the answer, recorded as such — following it
    would record the redirect target's body under the redirecting request's status."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))
_STANDARD_METHODS = ("DELETE", "GET", "HEAD", "OPTIONS", "POST", "PUT")
# Characters WHATWG URL parsing percent-encodes in a path or query; the rest of printable ASCII
# (including `%`, so nothing is encoded twice) is left alone.
_URL_SAFE = "".join(chr(c) for c in range(33, 127) if chr(c) not in '"<>`{}')


def do_request(base_url, req):
    """`fetch`, via urllib. What differs from Node's fetch and is not hidden: default request
    headers are set to the ones Node sends (user-agent, accept, accept-language, accept-encoding,
    sec-fetch-mode) so a server that logs or varies on them sees the same client; URL joining is
    urljoin plus percent-encoding rather than the WHATWG parser, which agrees on every path a
    request file realistically holds; a connection error is reported as "fetch failed", which is
    what undici's message says (the cause is on its `.cause`, which this script never printed)."""
    path = _uget(req, "path")
    base = urllib.parse.urlsplit(js_str(base_url))
    if base.scheme not in ("http", "https") or not base.netloc:
        raise Exception("Invalid URL")
    url = urllib.parse.quote(urllib.parse.urljoin(js_str(base_url), js_str(path)), safe=_URL_SAFE)

    method = _uget(req, "method")
    method = js_str(method) if js_truthy(method) and method is not UNDEF else "GET"
    if method.upper() in _STANDARD_METHODS:
        method = method.upper()
    hdrs = _uget(req, "headers")
    headers = {js_str(k): js_str(v) for k, v in (hdrs.items() if js_truthy(hdrs) and isinstance(hdrs, dict) else [])}
    body_v = _uget(req, "body")
    data = None
    if body_v is not UNDEF and body_v is not None:
        if method in ("GET", "HEAD"):
            raise Exception("Request with GET/HEAD method cannot have body.")
        data = (body_v if isinstance(body_v, str) else _stringify_text(body_v)).encode("utf-8", "replace")
        if not any(h.lower() == "content-type" for h in headers):
            headers["content-type"] = "application/json"
    lower = {h.lower() for h in headers}
    for k, v in (("user-agent", "node"), ("accept", "*/*"), ("accept-language", "*"),
                 ("sec-fetch-mode", "cors"), ("accept-encoding", "gzip, deflate")):
        if k not in lower:
            headers[k] = v

    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        try:
            res = _OPENER.open(r, timeout=300)
        except urllib.error.HTTPError as e:
            res = e  # 4xx/5xx and the 3xx _NoRedirect declined: fetch resolves with these too
        status = res.status if hasattr(res, "status") else res.code
        raw = res.read()
        enc = (res.headers.get("content-encoding") or "").lower()
        if enc == "gzip" or enc == "x-gzip":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:
        raise Exception("fetch failed")
    # res.text(): UTF-8, a leading BOM dropped, bad bytes replaced.
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        if not text:
            body = None
        else:
            body = _json_loads(text)
    except Exception:
        body = text
    return {"status": status, "body": body}


def read_unlock(root="."):
    p = _join(root, UNLOCK_FILE)
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
        return re.sub(r'^"|"\Z', "", js_trim(m.group(1)))

    return {"reason": get("reason") or "(no reason recorded)", "at": get("at") or "(unknown)", "by": get("by") or "unknown"}


def _iso_now():
    """Date.prototype.toISOString: UTC, millisecond precision, trailing Z."""
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def _yaml_str(s):
    return '"' + js_str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def to_yaml(value, indent=0):
    """Minimal YAML emitter for trace files. Only the shapes a trace holds: scalars, arrays,
    nested maps. Kept here rather than pulling PyYAML's dump so the written file's layout
    is stable run to run — a trace is evidence, and a formatter that reflows it on a library
    upgrade would show up as a diff on every trace in the repo. (It also means this layout is
    the Node version's, quirks included: a bare `true` or `null` string is written unquoted,
    and a nested empty map is written as a key with nothing after it. Changing either would
    reflow every committed trace.)"""
    pad = " " * indent

    def scalar(v):
        if v is None or v is UNDEF:
            return "null"
        if isinstance(v, (bool, int, float)):
            return js_str(v)
        s = js_str(v)
        return s if re.fullmatch(r"[\w./@-]+", s, re.ASCII) and not re.fullmatch(r"\d+", s, re.ASCII) else _quote(s)

    def is_obj(v):
        return isinstance(v, (list, dict))

    if isinstance(value, list):
        if not value:
            return "[]"
        parts = []
        for v in value:
            if is_obj(v):
                rest = re.sub(r"^\n?", "", to_yaml(v, indent + 2), count=1).lstrip(JS_WS)
                parts.append(f"{pad}- {rest}")
            else:
                parts.append(f"{pad}- {scalar(v)}")
        return "\n" + "\n".join(parts)
    if isinstance(value, dict):
        lines = []
        for k, v in js_items(value):
            key = "#" if k == "//" else f"{k}:"
            if k == "//":
                lines.append(f"{pad}# {js_str(v)}")
                continue
            if is_obj(v):
                rendered = to_yaml(v, indent + 2)
                lines.append(f"{pad}{key}{rendered}" if rendered.startswith("\n") else f"{pad}{key} {rendered}")
            else:
                lines.append(f"{pad}{key} {scalar(v)}")
        return ("\n" if indent else "") + "\n".join(lines) + ("" if indent else "\n")
    return scalar(value)


def _esc(s):
    return js_str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _first_line(e):
    return js_str(str(e)).split("\n")[0]


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

    def arg_after(f):
        return (argv[argv.index(f) + 1] if argv.index(f) + 1 < len(argv) else None) if f in argv else None

    def has(f):
        return f in argv

    def arg(n):
        return argv[n] if len(argv) > n else None

    by = arg_after("--by") or os.environ.get("USER") or "unknown"
    now = _iso_now()

    def log_decision(line):
        os.makedirs(EQUIV_DIR, exist_ok=True)
        if not os.path.exists(DECISION_LOG):
            _write(DECISION_LOG, "# Equivalence trace decisions\n\n"
                   "Every suspension of the trace-protection rule, every restoration of it, and every\n"
                   "accepted difference between the legacy system and the rebuild, in order.\n"
                   "Written by `python3 scripts/equiv.py unlock|relock|accept`. Do not edit by hand — the point of\n"
                   "the log is that it records what happened, not what someone remembers happening.\n\n"
                   "`gate.py lock gate-5` reads the `accepted:` lines below and refuses to lock while the\n"
                   "newest equivalence run has a failure that none of them names.\n\n")
        _write(DECISION_LOG, line, "a")

    # ---- status -------------------------------------------------------------
    if cmd == "status":
        reasons = _gate_reasons()
        if reasons:
            print("Equivalence lane: DOES NOT APPLY to this workbench.\n")
            for r in reasons:
                print(f"  - {r}\n")
            return 0
        traces = _trace_files(None)
        u = read_unlock()
        print("Equivalence lane: applies (own-code, reference runs).")
        print(f"  {len(traces)} trace(s) recorded under {EQUIV_DIR}/")
        by_feature = {}
        for t in traces:
            f = _parent_name(t)
            by_feature[f] = by_feature.get(f, 0) + 1
        # [...map].sort() with no comparator sorts the "feature,count" strings.
        for f, n in sorted(by_feature.items(), key=lambda kv: _u16(f"{kv[0]},{kv[1]}")):
            print(f"    {f}: {n}")
        print(f"\n  Traces: UNLOCKED since {u['at']} by {u['by']}\n    reason: {u['reason']}\n"
              "  Re-lock as soon as the change is made: python3 scripts/equiv.py relock"
              if u else "\n  Traces: protected. Editing a committed *.trace.yaml is blocked by the hook.")
        return 0

    # ---- record -------------------------------------------------------------
    if cmd == "record":
        _require_gate("record")
        feature_id = arg(1)
        if not feature_id or feature_id.startswith("--"):
            print("Usage: equiv record <feature-id>", file=sys.stderr)
            return 1
        cfg = _read_config()
        if not cfg:
            print(f"No {CONFIG_FILE}. Create it first — it names the two systems and the adapter:\n\n"
                  "adapter: postgres\n"
                  "legacy:\n  base_url_env: EQUIV_LEGACY_URL\n  database_url_env: EQUIV_LEGACY_DB\n"
                  "rebuild:\n  base_url_env: EQUIV_REBUILD_URL\n  database_url_env: EQUIV_REBUILD_DB\n\n"
                  "Env var NAMES, not values: this directory is committed, and a DSN with a password in "
                  "it is a credential in version control.", file=sys.stderr)
            return 1
        reqs = _request_files(feature_id)
        if not reqs:
            print(f"No *.request.yaml under {_join(EQUIV_DIR, feature_id)}/.\n\n"
                  "A trace is recorded FROM a request you author, out of the feature's UX flows and its "
                  "Rule Cards — this script drives the legacy system, it does not invent the traffic. One "
                  "file per behavior worth proving:\n\n"
                  f"  {_join(EQUIV_DIR, feature_id, 'issue-invoice.request.yaml')}\n\n"
                  f"    feature: {feature_id}\n"
                  "    rules: [R-BILL-002]        # optional; puts this trace in parity's per-rule column\n"
                  "    tables: [invoices]         # optional; snapshotted by the adapter before and after\n"
                  "    ignore:                    # fields the rebuild MAY differ on. Declared, never guessed\n"
                  "      - $.id\n"
                  "      - $.created_at\n"
                  "    request:\n      method: POST\n      path: /api/invoices\n      body: { customer_id: 1 }\n",
                  file=sys.stderr)
            return 1
        legacy = _resolve_side(cfg, "legacy")
        if not legacy["baseUrl"]:
            print(f"No legacy base URL. config.yaml names {js_str(legacy['baseUrlEnv']) if js_truthy(legacy['baseUrlEnv']) else '(nothing)'}"
                  f"{', which is unset in this shell' if js_truthy(legacy['baseUrlEnv']) else ''}.", file=sys.stderr)
            return 1
        adapter_name = js_prop(cfg, "adapter")
        adapter_name = adapter_name if js_truthy(adapter_name) else "none"
        adapter = None if adapter_name == "none" else (ADAPTERS.get(adapter_name) if isinstance(adapter_name, str) else None)
        if adapter_name != "none" and not adapter:
            print(f'Unknown adapter "{js_str(adapter_name)}". Shipped: {", ".join(ADAPTERS.keys())}, or `none`.', file=sys.stderr)
            return 1

        os.makedirs(_join(EQUIV_DIR, feature_id), exist_ok=True)
        written = 0
        for rf in reqs:
            spec = yamlio.load(_read_text(rf))
            spec = spec if js_truthy(spec) else {}
            name = re.sub(r"\.request\.yaml$", "", os.path.basename(rf))
            out = _join(EQUIV_DIR, feature_id, f"{name}.trace.yaml")
            if os.path.exists(out) and not has("--force"):
                print(f"skip   {out} already exists (re-recording would overwrite evidence — --force to insist)")
                continue
            tables = js_prop(spec, "tables")
            tables = tables if js_truthy(tables) else []
            rows_before = rows_after = None

            def snapshot(when, name=name, tables=tables):
                try:
                    return adapter.capture(tables, legacy["db"])
                except Exception as e:
                    print(f"Cannot snapshot {js_join(tables, ', ')} on the LEGACY side ({when} the request), "
                          f"recording {name}:\n  {js_str(str(e))}", file=sys.stderr)
                    db_env = legacy["dbEnv"]
                    print(f"\n  config.yaml's legacy.database_url_env names "
                          f"{js_str(db_env) if js_truthy(db_env) else '(nothing)'}"
                          f"{', currently ' + ('set' if os.environ.get(js_str(db_env)) else 'UNSET') if js_truthy(db_env) else ''}.",
                          file=sys.stderr)
                    print("  Nothing was written. A trace with half a snapshot is worse than no trace: "
                          "it would replay green against a rebuild that persists nothing.", file=sys.stderr)
                    sys.exit(1)

            if adapter and len(tables):
                why = adapter.available(legacy["db"])
                if why:
                    print(f"Cannot snapshot tables for {name}: {why}.", file=sys.stderr)
                    return 1
                rows_before = snapshot("before")
            request = js_prop(spec, "request")
            try:
                res = do_request(legacy["baseUrl"], request if js_truthy(request) else {})
            except Exception as e:
                print(f"Request failed against the LEGACY system for {name}: {_first_line(e)}", file=sys.stderr)
                print("Nothing recorded. The legacy system has to be up and reachable to record against it.", file=sys.stderr)
                return 1
            if adapter and len(tables):
                rows_after = snapshot("after")

            rules = js_prop(spec, "rules")
            ignore = js_prop(spec, "ignore")
            doc = {
                "//": "Recorded against the LEGACY system before the rebuild existed. Do not edit: "
                      "`python3 scripts/equiv.py unlock --reason \"...\"` is the logged way to change an expectation.",
                "feature": feature_id,
                "rules": rules if js_truthy(rules) else [],
                "recorded_at": now,
                "recorded_by": by,
                "adapter": adapter_name if adapter and len(tables) else "none",
                "request": request if js_truthy(request) else {},
                "expect": {"status": res["status"], "body": res["body"]},
                "ignore": ignore if js_truthy(ignore) else [],
                "tables": tables,
            }
            if rows_before is not None:
                doc["rows_before"] = rows_before
                doc["rows_after"] = rows_after
            _write(out, to_yaml(doc))
            print(f"recorded {out}  (HTTP {res['status']}{f', {len(tables)} table(s) snapshotted' if len(tables) else ''})")
            written += 1
        print(f"\n{written} trace(s) recorded for {feature_id}.")
        print("Commit them now. A committed trace is protected by the hook; an uncommitted one "
              "is still being recorded and is free to edit.")
        return 0

    # ---- replay -------------------------------------------------------------
    if cmd == "replay":
        _require_gate("replay")
        feature_id = None if has("--all") else arg(1)
        if not feature_id and not has("--all"):
            print("Usage: equiv replay <feature-id> | --all", file=sys.stderr)
            return 1
        cfg = _read_config()
        rebuild = _resolve_side(cfg, "rebuild")
        if not rebuild["baseUrl"]:
            print(f"No rebuild base URL. config.yaml names {js_str(rebuild['baseUrlEnv']) if js_truthy(rebuild['baseUrlEnv']) else '(nothing)'}"
                  f"{', which is unset in this shell' if js_truthy(rebuild['baseUrlEnv']) else ''}.", file=sys.stderr)
            return 1
        traces = _trace_files(feature_id)
        if not traces:
            print(f"No *.trace.yaml under {_join(EQUIV_DIR, feature_id) if feature_id else EQUIV_DIR}/ — "
                  "record before you replay.", file=sys.stderr)
            return 1
        adapter_name = js_prop(cfg, "adapter")
        adapter_name = adapter_name if js_truthy(adapter_name) else "none"
        adapter = None if adapter_name == "none" else (ADAPTERS.get(adapter_name) if isinstance(adapter_name, str) else None)

        cases = []
        for tf in traces:
            t = yamlio.load(_read_text(tf))
            t = t if js_truthy(t) else {}
            name = re.sub(r"\.trace\.yaml$", "", os.path.basename(tf))
            feature = js_prop(t, "feature")
            feature = feature if js_truthy(feature) else _parent_name(tf)
            # classname carries the feature id and any rule ids, because that is the only thing JUnit
            # transports — acsuite.py groups the equivalence run by both, exactly as it does the AC run.
            rules = js_prop(t, "rules")
            classname = js_join([feature, *(rules if js_truthy(rules) else [])], " ")
            diffs = []
            errored = None
            res = None
            tables = js_prop(t, "tables")
            tables = tables if js_truthy(tables) else []
            rows_after = None
            try:
                if adapter and len(tables) and js_truthy(js_prop(t, "rows_before")):
                    why = adapter.available(rebuild["db"])
                    if why:
                        raise Exception(why)
                    # The rebuild's rows are compared against the LEGACY's post-request snapshot: the
                    # question is what the request left behind, not what the database happened to hold.
                request = js_prop(t, "request")
                res = do_request(rebuild["baseUrl"], request if js_truthy(request) else {})
                if adapter and len(tables) and js_truthy(js_prop(t, "rows_after")):
                    rows_after = adapter.capture(tables, rebuild["db"])
            except Exception as e:
                errored = _first_line(e)

            if errored:
                cases.append({"name": name, "classname": classname,
                              "failure": f"request or snapshot failed against the rebuild: {errored}"})
                print(f"ERROR  {js_str(feature)} › {name}: {errored}")
                continue
            expect = js_prop(t, "expect")
            ignore = js_prop(t, "ignore")
            ignore = ignore if js_truthy(ignore) else []
            if not _strict_eq(_uget(expect, "status"), res["status"]):
                diffs.append({"path": "$.status", "legacy": _uget(expect, "status"), "rebuild": res["status"]})
            diffs.extend(diff_values(_uget(expect, "body"), res["body"], "$.body", ignore))
            if rows_after is not None:
                diffs.extend(adapter.diff(js_prop(t, "rows_after"), rows_after,
                                          ["$" + p[len("$.body"):] if p.startswith("$.body") else p for p in ignore]))

            if diffs:
                detail = "\n".join(f"  {d['path']}\n    legacy:  {_stringify_text(d['legacy'])}\n    rebuild: {_stringify_text(d['rebuild'])}"
                                   for d in diffs[:20])
                cases.append({"name": name, "classname": classname, "failure":
                              f"{len(diffs)} unignored difference(s) between the legacy system and the rebuild:\n{detail}"
                              + (f"\n  …and {len(diffs) - 20} more" if len(diffs) > 20 else "")})
                print(f"FAIL   {js_str(feature)} › {name}  ({len(diffs)} difference(s))")
            else:
                cases.append({"name": name, "classname": classname})
                print(f"ok     {js_str(feature)} › {name}")

        # Local calendar, like every dated file in parity/: parity.py looks this file up by
        # today's LOCAL date, and a UTC name is not found there on any local morning east of UTC.
        date = local_date()
        out = _join("parity", f"{date}-equiv.xml")
        os.makedirs("parity", exist_ok=True)
        failed = sum(1 for c in cases if "failure" in c)

        def case_xml(c):
            if "failure" in c:
                return (f'    <testcase classname="{_esc(c["classname"])}" name="{_esc(c["name"])}">\n'
                        f'      <failure message="not equivalent">{_esc(c["failure"])}</failure>\n    </testcase>')
            return f'    <testcase classname="{_esc(c["classname"])}" name="{_esc(c["name"])}"/>'

        _write(out,
               '<?xml version="1.0" encoding="UTF-8"?>\n'
               '<testsuites>\n'
               f'  <testsuite name="equivalence" tests="{len(cases)}" failures="{failed}">\n'
               + "\n".join(case_xml(c) for c in cases) + "\n"
               '  </testsuite>\n'
               '</testsuites>\n')
        print(f"\n{len(cases) - failed}/{len(cases)} trace(s) equivalent. Wrote {out}.")
        if failed:
            print("\nA red trace is a real difference, not a flaky test. Either the rebuild is wrong, "
                  "or the difference is intended — in which case say so on the record:")
            print('  python3 scripts/equiv.py accept "<trace name>" --reason "..."')
            print("`gate.py lock gate-5` refuses while the newest run has a failure no decision names.")
        return 1 if failed else 0

    # ---- accept -------------------------------------------------------------
    if cmd == "accept":
        trace = arg(1)
        reason = arg_after("--reason")
        if not trace or trace.startswith("--") or not reason:
            print('Usage: equiv accept "<trace name>" --reason "..."', file=sys.stderr)
            print("The trace name is the `name` attribute in the JUnit output — what `replay` printed.", file=sys.stderr)
            print("A reason is required: this is the record that a difference between the old system", file=sys.stderr)
            print('and the rebuild is intended. "the test is red" is not a reason; it is the situation.', file=sys.stderr)
            return 1
        log_decision(f"- **{now}** · accepted by {by}\n  - accepted: `{trace}`\n  - {reason}\n")
        print(f"Logged to {DECISION_LOG}: `{trace}` is an accepted difference.")
        print("gate-5 will no longer refuse to lock on it. It stays red in the report, which is "
              "correct — the difference is real and now it is also explained.")
        return 0

    # ---- unlock / relock ----------------------------------------------------
    if cmd == "unlock":
        reason = arg_after("--reason")
        if not reason:
            print('Unlocking requires --reason "..." — it is a formal, logged event, same as a gate reopen.', file=sys.stderr)
            print("Say which expectation is changing and why the recorded one was wrong. Remember what a", file=sys.stderr)
            print("trace IS: what the old system actually did, captured before the rebuild existed. Changing", file=sys.stderr)
            print("it to match the rebuild does not make them equivalent, it makes the evidence agree with", file=sys.stderr)
            print("the code — which is the one property this lane exists to have.", file=sys.stderr)
            return 1
        os.makedirs(EQUIV_DIR, exist_ok=True)
        _write(UNLOCK_FILE,
               "# Equivalence traces are temporarily unprotected. Written by scripts/equiv.py.\n"
               "# Re-lock with: python3 scripts/equiv.py relock\n"
               f"at: {now}\n"
               f"by: {_yaml_str(by)}\n"
               f"reason: {_yaml_str(reason)}\n")
        log_decision(f"- **{now}** · unlocked by {by}\n  - {reason}\n")
        print(f"Equivalence traces unlocked. Logged to {DECISION_LOG}.")
        print("Make the change, then: python3 scripts/equiv.py relock")
        return 0

    if cmd == "relock":
        u = read_unlock()
        if not u:
            print("Already protected — nothing to re-lock.")
            return 0
        os.remove(UNLOCK_FILE)
        log_decision(f"- **{now}** · re-locked by {by} (was unlocked {u['at']})\n")
        print(f"Equivalence traces re-locked. Logged to {DECISION_LOG}.")
        return 0

    print('Usage: equiv.py status | record <feature-id> | replay <feature-id>|--all | '
          'accept "<trace>" --reason "..." | unlock --reason "..." | relock', file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
