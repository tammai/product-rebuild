#!/usr/bin/env python3
"""evidence_bundle.py — verbatim line ranges into one file, for the rubric judge. Run from the workbench root.

  python3 scripts/evidence_bundle.py --out plan/gate-reviews/gate-4-evidence.md \\
      contracts/openapi/openapi.yaml:120-188 adr/ADR-003-auth.md:1-60 contracts/errors.yaml

WHY IT EXISTS. For a gate whose artifacts are big (a gate 3 ADR set, a gate 4 `openapi.yaml`), the judge scores
from a bundle of excerpts and opens a full file only when a dimension needs what the bundle left out
(subagent-briefs.md). The orchestrator wrote that bundle by hand, which means retyping hundreds of lines as
model output (about 7K output tokens a gate, and the slowest kind of token), and a retyped excerpt is not
verbatim: one run's "excerpt" had quietly fixed a typo the judge was supposed to score. Choosing WHICH ranges
the rubric's dimensions touch is the orchestrator's judgement and stays with it. Copying them is not, and this
does it, each under a heading `path:start-end` so the judge can open the same range.

A spec is `path:start-end` (1-based, inclusive) or a bare `path` for the whole file. A range past the end of the
file is clamped and says so in its heading; a missing file or a path that leaves the workbench is refused and
nothing is written.
"""
import os
import sys


def _opt(args, name, default=""):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def _split(spec):
    path, _, rng = spec.rpartition(":")
    if path and rng and all(p.isdigit() for p in rng.split("-", 1)) and 1 <= len(rng.split("-")) <= 2 and "-" in rng:
        a, b = rng.split("-", 1)
        return path, int(a), int(b)
    return spec, None, None


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    out = _opt(args, "--out")
    specs = [a for i, a in enumerate(args) if a != "--out" and not (i > 0 and args[i - 1] == "--out")]
    if not out or not specs:
        print("Usage: evidence_bundle.py --out <file> path[:start-end] [path[:start-end] ...]", file=sys.stderr)
        return 1
    root = os.path.realpath(".")
    parts = ["# Evidence bundle", "",
             "Verbatim excerpts copied by `evidence_bundle.py`, each headed `path:start-end`. A starting point, not a limit: open "
             "the full file for any range a dimension needs that is not here.", ""]
    for spec in specs:
        path, lo, hi = _split(spec)
        real = os.path.realpath(path)
        if not (real == root or real.startswith(root + os.sep)):
            print(f"evidence_bundle.py: {path} is outside the workbench; nothing written.", file=sys.stderr)
            return 1
        if not os.path.isfile(real):
            print(f"evidence_bundle.py: no such file: {path}; nothing written.", file=sys.stderr)
            return 1
        with open(real, encoding="utf-8", errors="replace", newline="") as f:
            lines = f.read().replace("\r\n", "\n").split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        if lo is None:
            lo, hi, note = 1, len(lines), ""
        else:
            if lo < 1 or hi < lo:
                print(f"evidence_bundle.py: bad range in {spec}; nothing written.", file=sys.stderr)
                return 1
            note = ""
            if hi > len(lines):
                note = f" (clamped: the file has {len(lines)} lines)"
                hi = len(lines)
            if lo > len(lines):
                print(f"evidence_bundle.py: {spec} starts past the end of the file ({len(lines)} lines); nothing written.", file=sys.stderr)
                return 1
        parts += [f"## {path}:{lo}-{hi}{note}", "", "```"] + lines[lo - 1:hi] + ["```", ""]
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(parts))
    print(f"Wrote {out}: {len(specs)} excerpt(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
