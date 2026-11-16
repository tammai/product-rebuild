#!/usr/bin/env python3
"""adapter.py — checks the reference adapter answered nothing by itself.

  python3 scripts/adapter.py audit [<log>]     # default parity/adapter/requests.jsonl

WHY IT EXISTS. When the rebuild's contract is not the reference's own API, rspec proves each recorded test on the
reference through an adapter: a service that serves openapi.json by calling the reference (the plugin's
docs/specs/contract-shaped-tests/design.md). The tests are only proven on the reference if every answer came from
it. An adapter that answers a call itself (a stub, a cached or invented body) makes a test pass against nothing,
and the build is then held to that. So the adapter logs each request it served with the number of reference
calls it made for it, and this audit fails on any response no reference call backs. A 501 (an operation it does
not map) or a gateway 502-504 (the reference is down) is the adapter declining: it can only fail a test, never
pass one, so it is not a finding.

THE LOG. parity/adapter/requests.jsonl, git-ignored: it names every recorded request, the hidden tests' too. The
adapter writes `{"start": "<ISO 8601 with timezone>"}` each time it starts, then one line per request (method,
path, status, reference_calls; no bodies). Every run started since the adapter's last commit is audited: verify
restarts the adapter mid-run, and each restart is a new run whose answers count. Runs of an older version are
not, so a fixed adapter's earlier answers never block Gate 4.

WHY A SCRIPT. Gate 4 refuses to lock on it (gate.py imports audit()), and a rule a gate enforces has to give the
same answer every time it is asked. Exit 0: every audited request is backed or declined; 1: one is not, or a line
is malformed; 2: not run (no log, no run of this version, or no request answered from the reference).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime

LOG = "parity/adapter/requests.jsonl"
DECLINED = (501, 502, 503, 504)


def parse_time(s):
    """An aware datetime from ISO 8601, or None: a time with no timezone can't be compared with git's dates."""
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def last_change():
    """When adapter/ was last committed (aware), or None when git can't say."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cI", "--", "adapter"], capture_output=True, text=True,
                             check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return parse_time(out) if out else None


def audit(path=LOG, since=None):
    """(exit code, report lines). Audits every run started at or after `since` (the adapter's last commit, so
    restarts mid-verify are all covered and an older version's runs are not); with no `since`, every run."""
    # The log is the adapter's output: its text is printed through json.dumps, never as raw terminal text.
    q = json.dumps
    try:
        with open(path, encoding="utf-8") as fh:
            raw = [(n, l) for n, l in enumerate(fh.read().splitlines(), 1) if l.strip()]
    except OSError:
        return 2, [f"not run: no adapter request log at {path}. The adapter writes one line per request it serves; "
                   f"run rspec:verify through it first."]
    bad, runs, current, undated = [], [], None, 0
    for n, line in raw:
        try:
            r = json.loads(line)
        except ValueError:
            r = None
        # Lines before this version's first run belong to an older one, malformed or not, and are skipped: a
        # fixed adapter's earlier output never blocks the gate. From that run on, nothing is skipped.
        if isinstance(r, dict) and "start" in r and "method" not in r:
            started = parse_time(r["start"])
            undated += started is None
            if started is None and runs:
                bad.append(f"  line {n}: start {q(r['start'])} needs an ISO 8601 time with a timezone (Z)")
            current = None if started is None or (since and started < since) else {"start": r["start"], "rows": []}
            if current:
                runs.append(current)
        elif current is not None:
            current["rows"].append((n, r))
    if not runs and not bad:
        after = f" since the adapter's last commit ({since.isoformat()})" if since else ""
        why = f" ({undated} start line(s) had no timezone, so none could be dated)" if undated else ""
        return 2, [f"not run: {path} has no run started{after}{why}: re-run rspec:verify through this version."]
    backed = total = 0
    for run in runs:
        for n, r in run["rows"]:
            total += 1
            calls, status = (r.get("reference_calls"), r.get("status")) if isinstance(r, dict) else (None, None)
            if not isinstance(r, dict) or not isinstance(r.get("method"), str) or not isinstance(r.get("path"), str) \
                    or type(status) is not int or type(calls) is not int or calls < 0:
                bad.append(f"  line {n}: needs method and path (text), status and reference_calls (whole numbers)")
            elif calls > 0:
                backed += 1
            elif status not in DECLINED:
                bad.append(f"  line {n}: {q(r['method'])} {q(r['path'])} answered {status} with no reference call")
    if bad:
        return 1, [f"{path}: {len(bad)} line(s) fail the audit:"] + bad
    if not backed:
        return 2, [f"not run: the {len(runs)} run(s) audited answered no request from the reference."]
    return 0, [f"{backed} of {total} requests in {len(runs)} run(s) answered from the reference; the rest declined (501-504)"]


def main(argv):
    if not argv or argv[0] != "audit" or len(argv) > 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    code, lines = audit(argv[1] if len(argv) > 1 else LOG, last_change())
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
