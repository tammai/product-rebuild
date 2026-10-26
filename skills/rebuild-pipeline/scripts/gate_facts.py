#!/usr/bin/env python3
"""gate_facts.py — the counts a gate's rubric asks the judge to work out, printed. Run from the workbench root.

  python3 scripts/gate_facts.py gate-1 [--out plan/gate-reviews/gate-1-facts.md]
  python3 scripts/gate_facts.py gate-2

WHY IT EXISTS. Two rubric dimensions are arithmetic and were done by the judge reading files one at a time:
gate-1 D3 (does every entity in the reference ERD appear in some feature's `ground_truth`, and every entity a
feature names exist in the ERD) and D2 (feature counts per domain), and gate-2 D2 (feature counts per slice).
A set difference over a few hundred names is something a script gets right every time and a reader gets right
most times, and the judge's attention is better spent on the dimensions that are judgement. The judge still
scores; this only hands it the numbers. Anything else in a rubric (is a `done_means` testable, does an
ordering hold) is not computable here and is left alone.

Entity names are compared on identity, not style, as validate.py does for Rule Cards: the ERD writes
WORK_PACKAGE, a feature may say `work package` or WorkPackage, and none of those is an orphan.
"""
import glob
import os
import re
import sys

import yamlio

try:
    import erd as erd_lib
except ImportError:  # a hand-upgraded workbench without erd.py loses the entity facts, not the counts
    erd_lib = None


def _norm(e):
    return re.sub(r"[^A-Z0-9]", "", str(e).upper())


def _load(path):
    if not os.path.exists(path):
        return None
    return yamlio.load(open(path, encoding="utf-8").read().replace("\r\n", "\n"))


def _spread(counts):
    vals = [v for v in counts.values() if v]
    if not vals:
        return "(none)"
    return f"smallest {min(vals)}, largest {max(vals)}, ratio {max(vals) / min(vals):.1f}x"


def gate1():
    feats = _load(os.path.join("matrix", "features.yaml")) or []
    out = ["## D2. Feature counts per domain (from matrix/features.yaml)", ""]
    per = {}
    for f in feats:
        per.setdefault(str((f or {}).get("domain") or "(no domain)"), []).append(str((f or {}).get("id")))
    for d in sorted(per):
        out.append(f"- {d}: {len(per[d])}")
    out += ["", f"Spread: {_spread({d: len(v) for d, v in per.items()})}.", "",
            "## D3. Entities, both directions", ""]
    erd_files = sorted(glob.glob(os.path.join("findings", "ground-truth", "reference-erd*.mermaid")))
    if not (erd_lib and erd_files):
        out.append("No findings/ground-truth/reference-erd*.mermaid (or erd.py is missing), so entities were not compared.")
        return out
    erd_names = {}
    for f in erd_files:
        for e in erd_lib.read_erd(f)["entities"]:
            erd_names.setdefault(_norm(e), e)
    feat_names = {}
    for f in feats:
        for e in ((f or {}).get("ground_truth") or {}).get("entities") or []:
            feat_names.setdefault(_norm(e), []).append(str(f.get("id")))
    in_erd_only = sorted(erd_names[k] for k in erd_names if k not in feat_names)
    in_feat_only = sorted((k, v) for k, v in feat_names.items() if k not in erd_names)
    out.append(f"ERD files: {', '.join(erd_files)}. {len(erd_names)} entities in the ERD, {len(feat_names)} named by features.")
    out += ["", f"In the ERD, named by no feature ({len(in_erd_only)}): " + (", ".join(in_erd_only) or "none")]
    out += ["", f"Named by a feature, absent from the ERD ({len(in_feat_only)}):"]
    out += [f"- {k}: {', '.join(v)}" for k, v in in_feat_only] or ["- none"]
    return out


def gate2():
    slices = _load(os.path.join("plan", "slices.yaml")) or []
    out = ["## D2. Feature counts per slice (from plan/slices.yaml)", ""]
    counts = {}
    for s in slices:
        counts[str((s or {}).get("id"))] = len((s or {}).get("features") or [])
        out.append(f"- {(s or {}).get('id')} ({(s or {}).get('name')}): {counts[str((s or {}).get('id'))]}")
    out += ["", f"Spread: {_spread(counts)}."]
    return out


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    gate = args[0] if args else ""
    fn = {"gate-1": gate1, "gate-2": gate2}.get(gate)
    if not fn:
        print("Usage: gate_facts.py gate-1|gate-2 [--out path]. Only those two gates have computable facts.", file=sys.stderr)
        return 1
    text = "\n".join([f"# Facts for {gate}", "", "Computed by `gate_facts.py`; the judge scores, these are only the numbers.", ""] + fn()) + "\n"
    if "--out" in args and args.index("--out") + 1 < len(args):
        dest = args[args.index("--out") + 1]
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"Wrote {dest}.")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
