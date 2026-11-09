#!/usr/bin/env python3
"""cost.py — append one run to the workbench's cost log (contracts C7, spec 05 P9). Run from the workbench root.

  python3 scripts/cost.py add --slice S3 --stage build --plugin sdlc --agent lane-worker --tier sonnet \\
      --wall-s 412 --turns 38 --tokens-in 182000 --tokens-out 9100 --result ok
  (--stage alone, without --slice, for runs before the slices: logs/cost.jsonl)

WHY. P9 has every orchestrated run leave a cost line, so a slice's cost shows beside its quality figures and 06's
token targets can be measured. bug-hunter writes its own (`--cost-log`); rspec and sdlc do not, so the
orchestrator records each subagent or plugin run it dispatched with this, from what the host reported. A token
count the host did not report is left out (`null` in the line), never guessed: C7 counts those separately.
Slice runs go to logs/<Sn>/cost.jsonl, where boundary.py sums them by stage.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

FIELDS = (("--plugin", "plugin"), ("--stage", "stage"), ("--agent", "agent"), ("--tier", "tier"), ("--result", "result"))


def _opt(args, name):
    return args[args.index(name) + 1] if name in args[:-1] else None


def log_path(slice_id=None):
    return os.path.join("logs", slice_id, "cost.jsonl") if slice_id else os.path.join("logs", "cost.jsonl")


def add(args):
    sid = _opt(args, "--slice")
    if sid and not re.fullmatch(r"S\d+", sid):
        return "--slice is S<n>"
    row = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for flag, key in FIELDS:
        v = _opt(args, flag)
        if not v:
            return f"{flag} is required"
        row[key] = v
    try:
        row["wall_s"] = float(_opt(args, "--wall-s") or "")
        row["turns"] = int(_opt(args, "--turns") or "")
    except ValueError:
        return "--wall-s (seconds) and --turns (a whole number) are required"
    for flag, key in (("--tokens-in", "tokens_in"), ("--tokens-out", "tokens_out")):
        v = _opt(args, flag)
        try:
            row[key] = int(v) if v not in (None, "", "null") else None
        except ValueError:
            return f"{flag} is a whole number, or null when the host did not report it"
    ordered = {k: row[k] for k in ("ts", "plugin", "stage", "agent", "tier", "wall_s", "turns", "tokens_in", "tokens_out", "result")}
    p = log_path(sid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(ordered, ensure_ascii=False) + "\n")
    print(f"logged {ordered['stage']} / {ordered['agent']} to {p}")
    return None


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("cost: no locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    if args[:1] != ["add"]:
        print("Usage: cost.py add [--slice <Sn>] --stage <s> --plugin <p> --agent <a> --tier <t> --wall-s <n> --turns <n> "
              "[--tokens-in <n>|null] [--tokens-out <n>|null] --result <r>", file=sys.stderr)
        return 1
    err = add(args[1:])
    if err:
        print(f"cost: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
