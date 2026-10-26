#!/usr/bin/env python3
"""rules_recall.py (eval) — E16: how much of a known rule set does lane R find?

  python3 <plugin>/skills/rebuild-pipeline/eval/rules_recall.py findings/rules/billing.yaml
  python3 <plugin>/skills/rebuild-pipeline/eval/rules_recall.py <cards.yaml> --record --model mid --note "baseline"
  python3 <plugin>/skills/rebuild-pipeline/eval/rules_recall.py --self-test

Lane R's precision is checked in every project: rubric-judge opens each transcribed citation
and sets `verification: re-derived`. Its recall never was. The exit criterion in g1-mining.md
counts routes that have *a* card, so a route with five rules and one card passes, and a brief
change could halve what the miner finds without anything turning red. This scores a lane R
output against fixtures/rules-recall/gold.yaml, a rule set written alongside its source, so
"did the brief change help" becomes two numbers compared across releases.

It is a script, not a rubric line, because the comparison has to be identical every time: a
judge reading the cards would score this release's run by a different hand than the last.
No model calls. Dispatching the miner is the manual half; see the fixture's README.md.

It decides nothing. Exit 0 whatever the score, 1 only on bad input or a failed --self-test:
a fixture is a measuring stick, and wiring a threshold into it would make the number the
target rather than the reading.

Runs from anywhere: the YAML reader is the plugin's own scripts/yamlio.py, found next to this
eval's directory. (The Node original borrowed a workbench's `yaml` package and refused to run
without one; there is nothing to borrow now.)

Port notes: ratios are written as JavaScript wrote them (`1`, not `1.0`; Math.round halves go
up), because the --json and --record output is compared across releases.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.realpath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
OPTS_WITH_VALUE = {"--fixture", "--model", "--note"}


def _read_text(path):
    # CRLF to LF on every text read: see playbook.py's read_text for the incident.
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


def _load_yaml(text):
    # Imported here, not at module level, so importing this file never needs the scripts
    # directory on the path; the scorer's pure functions stay importable on their own.
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    import yamlio
    return yamlio.load(text)


def _js_str(v):
    """String(v): a gold or card field is usually text, but YAML can hand back numbers and
    booleans, and `1.0` must print as JavaScript's "1", `True` as "true"."""
    if v is None:
        return "undefined"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        if v == int(v) and abs(v) < 1e21:
            return str(int(v))
    return str(v)


def _js_round(x):
    # Math.round: halves go up. Python's round() goes to even and would score 0.5/1000 steps
    # differently from the numbers already recorded in eval/runs/.
    return math.floor(x + 0.5)


def _is_integer(x):
    # Number.isInteger: a YAML `12` and a `12.0` are both integers in JavaScript.
    if isinstance(x, bool):
        return False
    return isinstance(x, int) or (isinstance(x, float) and math.isfinite(x) and x == int(x))


def _iso_now():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def local_date(d=None):
    """The LOCAL date, like every dated file in eval/runs and parity/ — see local_date() in
    scripts/acsuite.py. Copied, not imported: the eval must run from a workbench whose vendored
    acsuite may be older. If you change one, change both."""
    d = d or datetime.now()
    return f"{d.year}-{d.month:02d}-{d.day:02d}"


def _norm_path(p):
    """A miner may cite `reference-src/app/x.rb`, `./app/x.rb`, or a path from wherever it mounted
    the source. The gold path is relative to reference-src/, so compare on the suffix rather than
    fail a correct citation on where the miner happened to stand."""
    s = _js_str(p).replace("\\", "/")
    cut = s.rfind("reference-src/")
    if cut >= 0:
        s = s[cut + len("reference-src/"):]
    return re.sub(r"^\.?/", "", s)


def _same_path(card_path, gold_path):
    c = _norm_path(card_path)
    return c == gold_path or c.endswith(f"/{gold_path}")


def _text_of(card):
    parts = [card.get("given"), card.get("when"), card.get("then")]
    return " \n ".join(_js_str(x) for x in parts if x).lower()


def _missing_values(card, rule):
    text = _text_of(card)
    return [group for group in (rule.get("values") or [])
            if not any(_js_str(alt).lower() in text for alt in group)]


def _ratio(n, d):
    if not d:
        return None
    r = _js_round((n / d) * 1000) / 1000
    return int(r) if r == int(r) else r


def _unique(items):
    out = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


def score(gold, cards):
    """Score cards against gold. Pure, so --self-test exercises exactly what a real run does.

    Located: one evidence entry with a `line` falls inside one of a rule's locations. Only entries
    with a line count — a file-level citation could be anything in the file, and crediting it
    would reward the summarising that rule.schema.json's `line` requirement exists to stop.
    Matched: located AND the card's kind is one of the rule's kinds. A located card with the wrong
    kind is a near miss: the miner found the code but filed the rule under a different meaning,
    which is a different failure from not finding it and gets its own list.
    """
    rules = gold["rules"]
    position = {id(r): i for i, r in enumerate(rules)}
    by_rule = {r["id"]: {"rule": r, "cards": []} for r in rules}
    unmatched, near_misses, also_located = [], [], []
    matched_cards = 0

    for card in cards:
        lines = [e for e in (card.get("evidence") or [])
                 if isinstance(e, dict) and e.get("path") and _is_integer(e.get("line"))]
        located = [r for r in rules if any(
            any(_same_path(e["path"], loc["path"]) and loc["lines"][0] <= e["line"] <= loc["lines"][1]
                for e in lines)
            for loc in r["locations"])]
        if not located:
            unmatched.append(card)
            continue
        kind_ok = [r for r in located if card.get("kind") in r["kinds"]]
        if not kind_ok:
            near_misses.append({"card": card, "rules": [r["id"] for r in located],
                                "expected": _unique([k for r in located for k in r["kinds"]])})
            continue
        # A card located on several rules counts for ONE, and the rest are listed, not credited:
        # one card standing for two rules is usually two rules folded into one. Which one is decided
        # by the card's own text — the rule whose values it names most — then by a rule no card has
        # claimed yet, then by gold order. Gold order alone credited two cards citing the same line
        # (one about the currency default, one about the starting status) to the same rule, and
        # scored the rule the second card described as missed.
        def named(r):
            return len(r.get("values") or []) - len(_missing_values(card, r))

        pick = sorted(kind_ok, key=lambda r: (
            -named(r), 1 if by_rule[r["id"]]["cards"] else 0, position[id(r)]))[0]
        matched_cards += 1
        by_rule[pick["id"]]["cards"].append(card)
        if len(kind_ok) > 1:
            also_located.append({"card": card, "rules": [r["id"] for r in kind_ok if r is not pick]})

    results = []
    for r in rules:
        hits = by_rule[r["id"]]["cards"]
        strict_hit = next((c for c in hits if not _missing_values(c, r)), None)
        results.append({
            "id": r["id"], "kind": r["kinds"][0], "path_kind": r.get("path_kind"), "hard": r.get("hard"),
            "rule": r.get("rule"),
            "matched": [c.get("id") for c in hits],
            "strict": strict_hit is not None,
            "missing_values": ([g[0] for g in _missing_values(hits[0], r)] if hits and strict_hit is None else []),
        })

    def slice_by(key):
        out = {}
        for k in _unique([_js_str(x.get(key)) for x in results]):
            group = [x for x in results if _js_str(x.get(key)) == k]
            hit = len([x for x in group if x["matched"]])
            out[k] = {"total": len(group), "matched": hit, "recall": _ratio(hit, len(group))}
        return out

    found = len([x for x in results if x["matched"]])
    return {
        "metrics": {
            "gold": len(rules),
            "cards": len(cards),
            "recall": _ratio(found, len(rules)),
            "strict_recall": _ratio(len([x for x in results if x["strict"]]), len(rules)),
            "precision": _ratio(matched_cards, len(cards)),
            "near_misses": len(near_misses),
            "unmatched": len(unmatched),
            "by_kind": slice_by("kind"),
            "by_path_kind": slice_by("path_kind"),
        },
        "results": results, "nearMisses": near_misses, "unmatched": unmatched, "alsoLocated": also_located,
    }


def _pct(x):
    return "n/a" if x is None else f"{_js_round(x * 100)}%"


def render(result):
    m, results = result["metrics"], result["results"]
    near_misses, unmatched, also_located = result["nearMisses"], result["unmatched"], result["alsoLocated"]
    out = []
    out.append(f"Lane R recall: {_pct(m['recall'])} ({len([r for r in results if r['matched']])}/{m['gold']} gold rules), "
               f"strict {_pct(m['strict_recall'])}, precision {_pct(m['precision'])} of {m['cards']} card(s)")
    out.append("")
    out.append("By kind:      " + ", ".join(f"{k} {v['matched']}/{v['total']}" for k, v in m["by_kind"].items()))
    out.append("By path kind: " + ", ".join(f"{k} {v['matched']}/{v['total']}" for k, v in m["by_path_kind"].items()))

    missed = [r for r in results if not r["matched"]]
    if missed:
        out += ["", f"Missed ({len(missed)}):"]
        for r in missed:
            hard = f"\n         hard: {_js_str(r['hard'])}" if r["hard"] else ""
            out.append(f"  {r['id']} {r['kind']}/{_js_str(r['path_kind'])} — {_js_str(r['rule'])}{hard}")
    weak = [r for r in results if r["matched"] and not r["strict"]]
    if weak:
        out += ["", f"Found, but no card names the values a test would assert on ({len(weak)}):"]
        for r in weak:
            out.append(f"  {r['id']} via {', '.join(_js_str(x) for x in r['matched'])} — missing: {', '.join(_js_str(x) for x in r['missing_values'])}")
    if near_misses:
        out += ["", f"Near misses — right code, different kind ({len(near_misses)}):"]
        for n in near_misses:
            out.append(f"  {_js_str(n['card'].get('id'))} ({_js_str(n['card'].get('kind'))}) at {', '.join(n['rules'])}, expected {' or '.join(n['expected'])}")
    if also_located:
        out += ["", "Cards located on more than one rule (credited to one only; the others listed):"]
        for a in also_located:
            out.append(f"  {_js_str(a['card'].get('id'))} also at {', '.join(a['rules'])}")
    if unmatched:
        out += ["", f"Cards matching no gold rule ({len(unmatched)}) — a rule the gold set lacks, or a citation off its line:"]
        for c in unmatched:
            cid = c.get("id")
            then = c.get("then")
            out.append(f"  {'(no id)' if cid is None else _js_str(cid)} ({_js_str(c.get('kind'))}) — {'' if then is None else _js_str(then)[:140]}")
    return "\n".join(out)


# --- self-test ----------------------------------------------------------------------------------
# A scorer bug would read as a miner regression, so the scorer proves itself on inputs whose
# answer is known. The perfect cards are built from gold.yaml in memory rather than shipped as a
# file: a second copy of the answer is a second thing to keep in step with the source.
def self_test(gold):
    failures = 0

    def check(name, ok, detail=""):
        nonlocal failures
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            failures += 1
            if detail:
                print(f"      {detail}")

    def card_for(r, i, over=None):
        loc = r["locations"][0]
        card = {
            "id": f"R-BILL-{str(i + 1).rjust(3, '0')}", "kind": r["kinds"][0],
            "given": "", "when": "", "then": " ".join(_js_str(g[0]) for g in (r.get("values") or [])),
            "evidence": [{"path": f"reference-src/{loc['path']}", "commit": "0000000", "line": loc["lines"][0], "basis": "transcribed"}],
            "features": ["F-BILL-001"], "confidence": "high",
        }
        card.update(over or {})
        return card

    perfect = score(gold, [card_for(r, i) for i, r in enumerate(gold["rules"])])
    check("gold-as-cards scores 100% recall", perfect["metrics"]["recall"] == 1,
          json.dumps([x["id"] for x in perfect["results"] if not x["matched"]], separators=(",", ":"), ensure_ascii=False))
    check("gold-as-cards scores 100% strict recall", perfect["metrics"]["strict_recall"] == 1)
    check("gold-as-cards scores 100% precision", perfect["metrics"]["precision"] == 1, _js_str(perfect["metrics"]["precision"]))

    empty = score(gold, [])
    check("no cards: recall 0, precision n/a, no crash",
          empty["metrics"]["recall"] == 0 and empty["metrics"]["precision"] is None)

    r0 = gold["rules"][0]
    loc0 = r0["locations"][0]
    other_kind = next(k for k in ["calculation", "validation", "eligibility", "state-transition", "derivation"]
                      if k not in r0["kinds"])
    mis_kinded = score(gold, [card_for(r0, 0, {"kind": other_kind})])
    check("right line, wrong kind: a near miss, not a match",
          mis_kinded["metrics"]["near_misses"] == 1 and mis_kinded["metrics"]["recall"] == 0)

    off_line = score(gold, [card_for(r0, 0, {"evidence": [{"path": loc0["path"], "commit": "0000000", "line": 9999, "basis": "transcribed"}]})])
    check("a line outside every range matches nothing",
          off_line["metrics"]["unmatched"] == 1 and off_line["metrics"]["recall"] == 0)

    file_only = score(gold, [card_for(r0, 0, {"evidence": [{"path": loc0["path"], "commit": "0000000", "basis": "inferred"}]})])
    check("a file-level citation with no line is not credited", file_only["metrics"]["unmatched"] == 1)

    vague = score(gold, [card_for(r0, 0, {"then": "the amount is computed"})])
    check("a match whose then names no values counts for recall, not strict recall",
          vague["metrics"]["recall"] > 0 and vague["metrics"]["strict_recall"] == 0)

    dotted = score(gold, [card_for(r0, 0, {"evidence": [{"path": f"./{loc0['path']}", "commit": "0000000", "line": loc0["lines"][0], "basis": "transcribed"}]})])
    check("a ./-relative path matches the same rule", dotted["metrics"]["recall"] > 0)

    print(f"\n{failures} self-test failure(s)." if failures else "\nself-test passed.")
    return 1 if failures else 0


# --- main ---------------------------------------------------------------------------------------
def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        except Exception:
            pass
    args = list(sys.argv[1:] if argv is None else argv)

    def flag(name):
        return name in args

    def opt(name):
        if name not in args:
            return None
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else None

    files = [a for i, a in enumerate(args)
             if not a.startswith("--") and not (i > 0 and args[i - 1] in OPTS_WITH_VALUE)]

    fixture_dir = os.path.abspath(opt("--fixture") or os.path.join(HERE, "fixtures", "rules-recall"))
    gold = _load_yaml(_read_text(os.path.join(fixture_dir, "gold.yaml")))

    if flag("--self-test"):
        return self_test(gold)

    if not files:
        print("usage: rules_recall.py <lane-R output .yaml>... [--json] [--record] [--model <tier>] [--note <text>]\n"
              "       rules_recall.py --self-test", file=sys.stderr)
        return 1

    cards = []
    for f in files:
        if not os.path.exists(f):
            print(f"rules-recall: no such file {f}", file=sys.stderr)
            return 1
        data = _load_yaml(_read_text(f))
        if not isinstance(data, list):
            print(f"rules-recall: {f} is not an array of Rule Cards", file=sys.stderr)
            return 1
        cards.extend(data)

    result = score(gold, cards)
    print(json.dumps(result["metrics"], indent=2, ensure_ascii=False) if flag("--json") else render(result))

    if flag("--record"):
        entry_version = {}
        try:
            with open(os.path.join(HERE, "..", "..", "..", ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
                data = json.load(f)
            if "version" in data:
                entry_version["plugin_version"] = data["version"]
        except Exception:
            # Outside the plugin repo there is no plugin.json, and the record just has no version.
            entry_version["plugin_version"] = None
        directory = os.path.normpath(os.path.join(HERE, "runs", local_date()))
        file = os.path.join(directory, "rules-recall.json")
        os.makedirs(directory, exist_ok=True)
        log = []
        if os.path.exists(file):
            with open(file, encoding="utf-8") as f:
                log = json.load(f)
        # A missing version is left out, not null, exactly as JSON.stringify drops an undefined.
        # A failed read is null: the JavaScript initialised it to null and only overwrote on success.
        entry = {"at": _iso_now(), **entry_version, "model": opt("--model"), "note": opt("--note"),
                 "inputs": files, "metrics": result["metrics"],
                 "missed": [r["id"] for r in result["results"] if not r["matched"]]}
        log.append(entry)
        with open(file, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(log, indent=2, ensure_ascii=False) + "\n")
        print(f"\nrecorded → {file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
