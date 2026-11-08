#!/usr/bin/env python3
"""route.py — G6's router: every finding of a slice goes where contracts C6 says, one fix round at a time
(spec 05 P6). Run from the workbench root.

  python3 scripts/route.py <Sn>                 # route the slice's open findings as the next fix round
  python3 scripts/route.py <Sn> --close <ids>   # findings a fix round closed (comma-separated)

WHY A SCRIPT. G6 routing takes no judgement beyond C6's table (README topology: "orchestrator only"), and a
router that is prose gets a spec gap fixed in code, or a reference defect copied, depending on the session.
The table, by `finding-v1.class`: build-defect, test-defect -> an sdlc fix lane, one per feature per round,
the findings as its ACs (`lane_plan.py --fix`) · spec-gap -> `rspec:amend`, re-verify, then a fix lane ·
reference-defect -> the user: copy it, or add a departure · flaky, environment -> the orchestrator fixes the
harness · accepted-departure -> dropped. A finding a decided departure explains (it names the criterion) is
dropped too. Only a reproduced finding, or an sdlc spec question, is routed (C6); the rest are listed as not
routed. Validity and routes come from the plugin's own contracts.py, never a copy of the table.

WHERE FINDINGS COME FROM. `parity/findings/<Sn>/` (bug-hunter's `--out`, and the open-suite findings
boundary.py writes), the holdout repo's `findings/<Sn>/` (hidden-suite findings, kept out of every lane's
reach), and the human sample in `plan/slice-reviews/<Sn>.md`: each `differs: <what> (class: <class>)` line
becomes a finding here, with the reviewer as its verifier (a person comparing against the running reference is
the oracle, design rule 2). A hidden finding is listed by criterion and observed behaviour only, so a fix
round's file is safe to hand to a lane.

ROUND CAP. Two fix rounds per slice, as in sdlc's Review; a third is refused and the user decides (another
round, departures, or tickets). State lives in `plan/fix-rounds/<Sn>.json`; each round writes
`plan/fix-rounds/<Sn>-r<N>.md`.
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import sys

ROUND_CAP = 2
SECTIONS = ("sdlc", "rspec", "human", "orchestrator", "not routed", "dropped", "invalid")


def read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        return re.sub(r"\r\n?", "\n", fh.read())


def die(msg):
    print(f"route: {msg}", file=sys.stderr)
    return 1


def write(p, text):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def plugin_contracts():
    """The plugin's contracts.py as a module, found through the workbench's .rebuild-plugin marker, or None."""
    if not os.path.exists(".rebuild-plugin"):
        return None
    root = next((l.strip() for l in read_text(".rebuild-plugin").splitlines() if l.strip() and not l.startswith("#")), "")
    p = os.path.join(root, "contracts", "v1", "contracts.py")
    if not root or not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location("rebuild_contracts", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def state_path(sid):
    return os.path.join("plan", "fix-rounds", f"{sid}.json")


def load_state(sid):
    p = state_path(sid)
    st = json.loads(read_text(p)) if os.path.exists(p) else {}
    st.setdefault("rounds", [])
    st.setdefault("closed", [])
    st.setdefault("sample", {})
    return st


def sample_findings(sid, st, contracts):
    """Write a finding for each new `differs` line of the slice's human sample."""
    p = os.path.join("plan", "slice-reviews", f"{sid}.md")
    if not os.path.exists(p):
        return
    sec = re.search(r"^## Human sample\b([\s\S]*)\Z", read_text(p), re.M)
    if not sec:
        return
    who = re.search(r"Reviewer:[ \t]*([^\n·]+)", sec.group(1))
    reviewer = who.group(1).strip() if who else ""
    if not reviewer or reviewer.startswith("<"):
        return
    for m in re.finditer(r"^- (F-[A-Z0-9-]+):[ \t]*differs:[ \t]*(.+?)[ \t]*\(class:[ \t]*([a-z-]+)(?:,[ \t]*severity:[ \t]*(high|medium|low))?\)[ \t]*$",
                         sec.group(1), re.M):
        feature, what, cls, sev = m.group(1), m.group(2), m.group(3), m.group(4) or "medium"
        if feature in st["sample"] or cls not in contracts.ROUTES:
            continue
        fid = f"HS-{len(st['sample']) + 1:04d}"
        f = {"id": fid, "source": "human-sample", "class": cls, "severity": sev, "criterion": None, "rule": None,
             "feature": feature,
             "repro": {"runner": "cli", "manual": f"compare {feature} by hand against the running reference"},
             "observed": {"rebuild": what, "reference": "what the running reference does (human sample)"},
             "route": contracts.ROUTES[cls], "verified_by": {"agent": reviewer, "result": "reproduced"}}
        write(os.path.join("parity", "findings", sid, f"{fid}.json"), json.dumps(f, indent=2, ensure_ascii=False) + "\n")
        st["sample"][feature] = fid


def findings(sid):
    """[(path, finding, hidden?)] from the slice's findings folder and the holdout repo's."""
    try:
        import holdout
        hold = holdout.holdout_dir()
    except ImportError:
        hold = None
    out = []
    for folder, hidden in ((os.path.join("parity", "findings", sid), False),
                           (os.path.join(hold, "findings", sid) if hold else None, True)):
        for p in sorted(glob.glob(os.path.join(folder, "*.json"))) if folder else []:
            try:
                out.append((p, json.loads(read_text(p)), hidden))
            except ValueError:
                out.append((p, None, hidden))
    return out


def feature_of(f):
    return f.get("feature") or (f["criterion"].split(".")[0] if f.get("criterion") else None)


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        return die("no locks/pipeline.yaml here — run from the workbench root.")
    sid = args[0] if args else None
    if not sid or not re.fullmatch(r"S\d+", sid):
        return die("usage: route.py <Sn> [--close <id,id,...>]")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    st = load_state(sid)
    if "--close" in args[:-1]:
        ids = [i.strip() for i in args[args.index("--close") + 1].split(",") if i.strip()]
        st["closed"] = sorted(set(st["closed"]) | set(ids))
        write(state_path(sid), json.dumps(st, indent=2) + "\n")
        print(f"{sid}: closed {', '.join(ids)}")
        return 0
    contracts = plugin_contracts()
    if not contracts:
        return die("the plugin's contracts/v1/contracts.py was not found through .rebuild-plugin: not run.")
    sample_findings(sid, st, contracts)
    try:
        import departures
    except ImportError:
        departures = None
    groups = {k: [] for k in SECTIONS}
    by_feature = {}
    for path, f, hidden in findings(sid):
        if f is None:
            groups["invalid"].append(f"- {path}: not JSON")
            continue
        fid = f.get("id", os.path.basename(path))
        if fid in st["closed"]:
            continue
        issues = [m for s, m in contracts.check_finding(f) if s == "error"]
        if issues:
            groups["invalid"].append(f"- {fid}: {'; '.join(issues)}")
            continue
        observed = str((f.get("observed") or {}).get("rebuild", "")).replace("\n", " ")
        line = f"- {fid} ({f['severity']}, {f['class']}{', ' + f['criterion'] if f.get('criterion') else ''}): {observed}"
        if hidden:
            line = f"- {fid} ({f['severity']}, hidden test of {f.get('criterion')}): {observed}"
        route = contracts.finding_route(f)
        did = departures.explained_by(f["criterion"]) if departures and f.get("criterion") else None
        if route is None:
            groups["not routed"].append(f"{line} — verified_by: {f['verified_by'].get('result')}")
        elif route == "drop" or did:
            groups["dropped"].append(f"{line} — {did + ' explains it' if did else 'accepted departure'}")
        elif route == "sdlc":
            by_feature.setdefault(feature_of(f) or "other", []).append((fid, line))
        else:
            groups[route].append(line)
    routable = by_feature or groups["rspec"] or groups["human"] or groups["orchestrator"]
    if not routable:
        write(state_path(sid), json.dumps(st, indent=2) + "\n")
        print(f"{sid}: nothing to route ({len(groups['dropped'])} dropped, {len(groups['not routed'])} not routed, "
              f"{len(groups['invalid'])} invalid).")
        return 0
    n = len(st["rounds"]) + 1
    if n > ROUND_CAP:
        return die(f"{sid} has had {ROUND_CAP} fix rounds and findings are still open. As in sdlc's Review, the user "
                   f"decides: another round, departures for what stays different, or tickets.")
    for feat, items in sorted(by_feature.items()):
        lane = f"fix-r{n}-{feat.lower()}"
        ids = ",".join(i for i, _ in items)
        groups["sdlc"].append(f"### {feat}\n" + "\n".join(l for _, l in items) +
                              f"\n\n`python3 scripts/lane_plan.py {sid} {lane} --worktree <path> --fix {n} --findings {ids} "
                              f'--approved-by "<name>"`\n')
    titles = {"sdlc": "sdlc — a fix lane per feature, the findings as its ACs",
              "rspec": "rspec — spec gaps: rspec:amend (the user approves an MVP `then`), re-verify, then a fix lane",
              "human": "human — reference defects: copy the behaviour, or add a departure",
              "orchestrator": "orchestrator — flaky or environment: fix the harness",
              "not routed": "not routed — not reproduced by a fresh verifier (contracts C6)",
              "dropped": "dropped — accepted departures", "invalid": "invalid — not finding-v1"}
    body = [f"# Fix round {n}, {sid}", "", f"Round {n} of {ROUND_CAP}. Routed by `route.py` from contracts C6; close what a "
            f"round fixes with `route.py {sid} --close <ids>`.", ""]
    for k in SECTIONS:
        body += [f"## {titles[k]}", ""] + (groups[k] or ["- none"]) + [""]
    write(os.path.join("plan", "fix-rounds", f"{sid}-r{n}.md"), "\n".join(body))
    st["rounds"].append({"n": n, "sdlc": {feat: [i for i, _ in items] for feat, items in by_feature.items()}})
    write(state_path(sid), json.dumps(st, indent=2) + "\n")
    print(f"{sid}: fix round {n} -> plan/fix-rounds/{sid}-r{n}.md "
          f"(sdlc {sum(len(v) for v in by_feature.values())}, rspec {len(groups['rspec'])}, human {len(groups['human'])}, "
          f"orchestrator {len(groups['orchestrator'])}, dropped {len(groups['dropped'])}, not routed {len(groups['not routed'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
