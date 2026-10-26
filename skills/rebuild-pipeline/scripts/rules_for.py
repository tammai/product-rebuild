#!/usr/bin/env python3
"""rules_for.py — the Rule Cards one spec-writer needs, in full, plus a one-line index of the rest.
Run from the workbench root.

  python3 scripts/rules_for.py --features F-BILL-001,F-BILL-002 [--entities invoice,line_item] [--domains billing]
                               [--out plan/rules-for/S3-billing.md]

WHY IT EXISTS. Every spec-writer was handed the whole `findings/rules/<domain>.yaml` for every domain its
slice touches, so a module that implements three of a domain's fifty cards read all fifty, with their
evidence arrays, and paid for them again on every turn. The cards the module needs are the ones whose
`features` name one of the module's features, and the `invariant` cards whose `entities` the module writes
(an invariant has no trigger and no feature of its own, and each new writer must cite it: spec-writer.md).
Those come out in full. Every OTHER card comes out as one index line (id, kind, the start of its `then`),
because the spec-writer is also asked to name "rules not covered by this module", which it cannot do for a
card it has never seen. So nothing is dropped: a card is in full, or in the index with its id, and the
writer opens the full card in findings/rules/<domain>.yaml when the index line makes it relevant. The
index line says how many cards were filtered, so a reader cannot take a short file for a whole domain.

It is a script, not a line in the brief, because "include the relevant ones" is the sentence a model gets
wrong silently in the direction of leaving a rule out, and a missing rule is invisible in a spec.
Zero-dependency beyond the vendored yamlio, like the scripts it sits with.
"""
import glob
import json
import os
import re
import sys

import yamlio

INDEX_WIDTH = 110


def _opt(args, name, default=""):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def _csv(s):
    return [x.strip() for x in s.split(",") if x.strip()]


def _domain_files(domains):
    if domains:
        return [os.path.join("findings", "rules", f"{d}.yaml") for d in domains]
    return sorted(glob.glob(os.path.join("findings", "rules", "*.yaml")))


def select(cards, features, entities):
    """(full, indexed) for one domain's cards."""
    full, indexed = [], []
    fset, eset = set(features), set(entities)
    for c in cards:
        c_features = set(c.get("features") or [])
        c_entities = set(c.get("entities") or [])
        take = bool(c_features & fset) or (c.get("kind") == "invariant" and bool(c_entities & eset))
        (full if take else indexed).append(c)
    return full, indexed


def _index_line(c):
    then = re.sub(r"\s+", " ", str(c.get("then") or "")).strip()
    if len(then) > INDEX_WIDTH:
        then = then[:INDEX_WIDTH - 1].rstrip() + "…"
    return f"- {c.get('id')} [{c.get('kind')}] {then}"


def build(features, entities, domains):
    out = ["# Rule Cards for this module", "",
           f"Features: {', '.join(features) or '(none given)'}  ·  entities written: {', '.join(entities) or '(none given)'}", "",
           "Cards in full are the ones that name one of this module's features, and the `invariant` cards on entities "
           "it writes. Every other card is one index line below it. Open the full card in `findings/rules/<domain>.yaml` "
           "for any index line that looks like this module's business, and list the ones you leave to other modules under "
           "**Rules not covered by this module**.", ""]
    total_full = total_idx = 0
    for path in _domain_files(domains):
        if not os.path.exists(path):
            out += [f"## {os.path.basename(path)}", "", f"(no such file: {path})", ""]
            continue
        cards = yamlio.load(open(path, encoding="utf-8").read().replace("\r\n", "\n")) or []
        full, indexed = select(cards, features, entities)
        total_full += len(full)
        total_idx += len(indexed)
        out += [f"## {os.path.basename(path)}: {len(full)} in full, {len(indexed)} filtered to the index, {len(cards)} cards in all", ""]
        for c in full:
            out += ["```json", json.dumps(c, indent=2, ensure_ascii=False), "```", ""]
        if indexed:
            out += ["Index of the other cards:", ""] + [_index_line(c) for c in indexed] + [""]
    out.append(f"({total_full} cards in full, {total_idx} in the index.)")
    return "\n".join(out) + "\n"


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1
    features = _csv(_opt(args, "--features"))
    if not features:
        print("Usage: rules_for.py --features F-A-001,F-A-002 [--entities a,b] [--domains d1,d2] [--out path]", file=sys.stderr)
        return 1
    text = build(features, _csv(_opt(args, "--entities")), _csv(_opt(args, "--domains")))
    out = _opt(args, "--out")
    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"Wrote {out}. " + text.strip().splitlines()[-1])
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
