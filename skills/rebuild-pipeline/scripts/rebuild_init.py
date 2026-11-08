#!/usr/bin/env python3
"""rebuild_init.py — scaffold a workbench repo for a product rebuild project.
Usage: python3 rebuild_init.py <project-name> [--dir <parent-dir>]
Standard library only.

It is a script and not a doc because a workbench is a pinned, self-contained copy of the tooling
(schemas, scripts, the vendored YAML reader) plus a provenance manifest, and a hand-written
checklist for that drifts from the file list within a release. The generated workbench needs
nothing installed beyond Python 3.9+: no package manager, no dependency step.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMAS = os.path.normpath(os.path.join(HERE, "..", "schemas"))

# rspec writes the spec into docs/ (its single-repo layout, 05 P2); adr/ holds only the vendored
# playbook and its scaffold manifest (playbook.py vendor), never ADRs, which are rspec's docs/decisions/.
DIRS = [
    "docs", "plan", "adr", "locks", "parity", "parity/flows", "parity/equiv",
    "schemas", "scripts",
    ".github/workflows",
]

# The vendored script set. If you change this list, change upgrade.py's VENDORED discovery
# too: it enumerates the plugin's scripts/ instead of carrying a list, so a script added here
# but living outside scripts/ would be scaffolded and never upgraded.
SCRIPTS = [
    "validate.py", "gate.py", "parity.py", "pause_check.py",
    "playbook.py", "flows.py", "autopilot.py",
    "sequence.py", "slice_review.py", "acsuite.py", "routing.py",
    "preflight.py", "upgrade.py", "equiv.py", "lanes_check.py",
    "lane_plan.py", "run_phases.py", "boundary.py",
    "holdout.py", "departures.py", "route.py", "gp.py", "cost.py",
    # The YAML and JSON-schema readers every checking script imports, and the PyYAML they sit on.
    "yamlio.py", "schemacheck.py",
]
VENDOR_TREE = os.path.join("_vendor", "pyyaml")


def _ignore_bytecode(_dir, names):
    # A __pycache__ in the plugin checkout is local state; copying it would hash a file that
    # differs per interpreter and make every workbench read as modified against the plugin.
    return [n for n in names if n == "__pycache__" or n.endswith(".pyc")]


def _iso_now():
    t = datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _vendored_files(scripts_dir):
    """Files under a workbench's scripts/ that belong to the vendored set, as scripts/-relative
    paths with `/`: top-level scripts plus the vendored PyYAML tree, never bytecode."""
    out = []
    for f in sorted(os.listdir(scripts_dir)):
        if os.path.isfile(os.path.join(scripts_dir, f)) and not f.endswith(".pyc"):
            out.append(f)
    tree = os.path.join(scripts_dir, VENDOR_TREE)
    for dirpath, dirs, names in os.walk(tree):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for n in sorted(names):
            if not n.endswith(".pyc"):
                rel = os.path.relpath(os.path.join(dirpath, n), scripts_dir)
                out.append(rel.replace(os.sep, "/"))
    return out


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    name = args[0] if args else None
    if not name or name.startswith("--"):
        print("Usage: python3 rebuild_init.py <project-name> [--dir <parent-dir>]", file=sys.stderr)
        return 1
    parent = args[args.index("--dir") + 1] if "--dir" in args else os.getcwd()
    root = os.path.normpath(os.path.join(parent, f"{name}-workbench"))
    if os.path.exists(root):
        print(f"Refusing to overwrite existing directory: {root}", file=sys.stderr)
        return 1

    for d in DIRS:
        os.makedirs(os.path.join(root, d), exist_ok=True)

    # Pin schemas + tooling scripts into the workbench (self-contained, versioned copy).
    shutil.copytree(SCHEMAS, os.path.join(root, "schemas"), dirs_exist_ok=True, ignore=_ignore_bytecode)
    for s in SCRIPTS:
        shutil.copy(os.path.join(HERE, s), os.path.join(root, "scripts", s))
    shutil.copytree(os.path.join(HERE, VENDOR_TREE), os.path.join(root, "scripts", VENDOR_TREE),
                    ignore=_ignore_bytecode)

    # Where this workbench came from, and what it came with.
    #
    # `.rebuild-plugin` is how scripts/upgrade.py finds the plugin later. It cannot rely on
    # CLAUDE_PLUGIN_ROOT: a workbench outlives the session that made it, and an env var pointing
    # at a plugin copy that has since moved would upgrade from the wrong source silently.
    #
    # `locks/tooling.json` is the provenance baseline. Without it, upgrade.py can see that a
    # vendored file differs from the plugin's but not WHY — an old copy and a local edit look
    # identical — so it would either nag about every stale file or overwrite someone's work. The
    # hashes recorded here are what make "unmodified, just behind" a decidable question.
    plugin_root = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
    write_raw(root, ".rebuild-plugin",
              "# Where this workbench's vendored scripts/ and schemas/ came from.\n"
              "# Read by scripts/upgrade.py. Edit if the plugin moves.\n"
              f"{os.path.abspath(plugin_root)}\n")

    plugin_version = "unknown"
    try:
        with open(os.path.join(plugin_root, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            plugin_version = json.load(fh).get("version", _MISSING)
    except Exception:
        plugin_version = "unknown"
    vendored_hashes = {}
    for f in _vendored_files(os.path.join(root, "scripts")):
        if f == "rebuild_init.py":
            continue
        vendored_hashes[f"scripts/{f}"] = _sha(os.path.join(root, "scripts", f))
    for f in sorted(os.listdir(os.path.join(root, "schemas"))):
        vendored_hashes[f"schemas/{f}"] = _sha(os.path.join(root, "schemas", f))
    # The two stray words in `comment` below are carried over verbatim from rebuild-init.mjs,
    # where a pair of backticked names was lost to a string-escape typo; upgrade.py writes the
    # intact sentence on its first apply. Fix both together if the sentence is ever repaired.
    manifest = {
        "comment": "Provenance of the vendored scripts/ and schemas/.  is the hash each file had "
                   "when it was last vendored, which is how upgrade.py tells a stale copy from one edited here. "
                   " records files whose local version a human chose to hold. Do not hand-edit.",
    }
    if plugin_version is not _MISSING:
        manifest["plugin_version"] = plugin_version
    manifest["updated"] = _iso_now()
    manifest["files"] = vendored_hashes
    manifest["kept"] = {}
    write_raw(root, os.path.join("locks", "tooling.json"), json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    def write(p, c):
        write_raw(root, p, c.replace("@@NAME@@", name).lstrip())

    write("sources.yaml", SOURCES_YAML)
    write("license-posture.md", LICENSE_POSTURE)
    write("repos.yaml", REPOS_YAML)
    write("rebuild.yaml", REBUILD_YAML)
    write("adr/README.md", ADR_README)
    write("parity/flows/README.md", FLOWS_README)

    # rspec's artifacts in its single-repo layout (docs/), in rspec's order (05 P2): the numbers
    # keep their 2.x names. gate.py's lock checks name the rspec step each one waits for.
    gates = [
        ("gate-1", "Feature lock", ["docs/features.md", "docs/domain.md", "docs/departures.yaml"]),
        ("gate-3", "Architecture lock", ["docs/decisions/", "adr/"]),
        ("gate-2", "Slice-plan lock", ["docs/build-plan.md"]),
        ("gate-4", "Contract lock", ["docs/openapi.json", "docs/schemas/", "docs/criteria.lock.json",
                                     "docs/acceptance/manifest.json"]),
        ("gate-5", "Prod-ready lock", ["docs/production-readiness.md", "parity/gp/nfr-evidence.md"]),
    ]
    for gid, title, protects in gates:
        listing = "\n".join(f"  - {p}" for p in protects)
        write(f"locks/{gid}.yaml", f"\ngate: {gid}\ntitle: {title}\nstatus: open\nprotects:\n{listing}\nhistory: []\n")
    write("locks/pipeline.yaml", PIPELINE_YAML.replace("@@NOW@@", _iso_now()))

    write(".github/workflows/validate.yml", VALIDATE_YML)

    # `.unlocked.yaml` is transient state, and gitignoring it is not tidiness. Committed while
    # active it would ship a workbench whose flow guard is off to every clone, silently; and
    # `gate.py lock` refuses to lock against a dirty tree, so an untracked one would block a gate
    # on a file that has nothing to do with the gate. `DECISIONS.md` is the opposite — it is the
    # log, and it is meant to be committed.
    #
    # __pycache__ is ignored for the same dirty-tree reason: running any script here writes
    # bytecode beside it, and an untracked scripts/__pycache__ would refuse the next gate lock.
    #
    # docs/acceptance/ and rspec's verify log are ignored until holdout.py split removes these lines (holdout.IGNORE_LINES; change
    # both together): rspec:verify records the whole bundle, and a commit before the split would put the
    # hidden share into the history every lane holds as a submodule.
    write(".gitignore", "__pycache__/\n*.pyc\nparity/flows/.unlocked.yaml\nparity/equiv/.unlocked.yaml\ndocs/acceptance/.unlocked.yaml\n"
          "# The bundle stays out of git until holdout.py split (05 P4): its hidden share must never be in\n"
          "# this repo's history, which every lane holds as a submodule. The split removes these lines.\n"
          "docs/acceptance/\ndocs/verify/runs.jsonl\n")

    write("README.md", README)

    try:
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "workbench: scaffold"]):
            subprocess.run(cmd, cwd=root, check=True, stdout=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        print("git init skipped (git unavailable?) — initialize manually.", file=sys.stderr)

    print(f"Workbench created: {root}")
    print("Next: fill sources.yaml and license-posture.md (G0).")
    print("Then give it a remote — this scaffold is currently the only copy:")
    print(f"  gh repo create {name}-workbench --private --source . --push")
    return 0


_MISSING = object()


def write_raw(root, p, content):
    # newline="\n": a scaffold made on Windows must hash and diff the same as one made elsewhere.
    full = os.path.join(root, p)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


SOURCES_YAML = '''
# What agents may read. Derived from license-posture.md — keep them consistent.
project: @@NAME@@
reference:
  name: ""            # e.g. openproject
  repo: ""            # clone URL; leave empty in clean-room mode
  pinned_commit: ""   # fill after first clone; every `[code]` citation in the spec uses this
  checkout: ""        # local path to that clone; scripts/preflight.py checks its HEAD
                      # against pinned_commit before rspec's discovery starts
  license: ""         # e.g. GPL-3.0, MIT
  kind: ""            # third-party | own-code (an app you already own and are replacing)
  # Who may read what (05 P3). strict: the spec side only observes behaviour; observe (the default
  # for third-party): the spec side may also read the code; own-code (the default for kind own-code):
  # build lanes may read it too. Build lanes never read the reference under strict or observe, and
  # never the hidden tests: hooks/scripts/reference_guard.py denies both. Which posture a licence
  # allows is the user's call at G0.
  posture: ""         # strict | observe | own-code; empty: own-code for kind own-code, else observe
  upstream: ""        # active | frozen — frozen turns off G6's upstream re-mine
  # How the reference runs on this machine, in one place. Moving its port in the Kutt rebuild
  # meant editing three places that had to agree by hand.
  run:
    compose: []       # compose files in order: upstream's, then overrides kept OUTSIDE the checkout
    base_url: ""      # where it answers (also list it under allowed:)
    accounts: ""      # how an agent signs in or seeds one: a credentials file outside the repo, or a command
# Which architecture playbook the stack comes from, and what this rebuild's output IS. Before
# rspec:tech, `python3 scripts/playbook.py vendor` copies the playbook and its scaffold manifest to
# adr/ (gate-3 locks them with the ADRs) and its stack line becomes rspec's stack preference; G5
# creates code repos from that manifest. Leave playbook empty for the org default; `none` makes
# every stack decision blank-slate, and you write adr/scaffold.json yourself.
architecture:
  playbook: ""        # e.g. web-modular-monolith | mobile-flutter | playbooks/ours.md | none
  target_shape: ""    # fullstack | client-only (client-only = the API already exists and stays)
allowed:
  - ""                # docs base URL, changelog URL, running-instance URL...
denied:
  - ""                # explicit deny list (e.g. the repo itself in clean-room mode)
'''

LICENSE_POSTURE = '''
# License posture — decide BEFORE rspec's discovery reads the reference

status: draft   # draft | decided

## Reference license
<!-- e.g. GPL-3.0 -->

## Distribution intent
<!-- private-learning | possible-closed-distribution | permissive-reference -->

## Consequence for reference.posture (sources.yaml)
<!-- strict: behaviour, docs and API only | observe: the spec side may read the code | own-code -->

## Prior attempts
<!-- Has this rebuild been tried before? By whom, how far it got, why it stopped, and
     what survives (a branch, a schema, a doc). "No" is a complete answer — write it. -->

## Off-limits
<!-- What may agents not touch or read: paths, repos, systems, data, people's inboxes.
     Anything here that is a path or a URL ALSO belongs in sources.yaml `denied:` — agents
     read that list, not this prose. "Nothing" is a complete answer — write it. -->

## Rationale
<!-- Why this posture. Note: this playbook is process, not legal advice. -->
'''

REPOS_YAML = '''
# Code repos consuming this workbench (fill after Gate 3).
# Each pins the workbench as a read-only submodule at a gate-4 tag.
# Populate as each repo is created — scripts/pause_check.py reads this to know which
# repos to check for uncommitted or unpushed work before a session pauses. A repo missing
# from this list is invisible to it and never checked. Format:
#   repos:
#     - name: <repo-name>
#       path: ../<repo-name>   # relative to this workbench's own root
repos: []
'''

# A file is the only way adr/ survives a clone before `vendor` runs: git does not track empty directories.
ADR_README = '''
# adr/ — the vendored playbook and its scaffold manifest

Not ADRs: those are rspec's, in `docs/decisions/`. This folder holds the architecture playbook the
stack comes from (`playbook.md`) and the scaffold manifest every code repo is created from
(`playbook.scaffold.json`, or `scaffold.json` with `architecture.playbook: none`).
`python3 scripts/playbook.py vendor` copies them here before rspec:tech, and gate-3 locks this folder
with the ADRs, so the stack a code repo is created from cannot change under the project when the
plugin upgrades.
'''

FLOWS_README = '''
# AC flows — the acceptance-criteria suite

One directory per feature, one flow file per acceptance criterion:
`parity/flows/<feature-id>/<criterion>.yaml`.

**Only populated under a playbook that says so** — today that is
`playbooks/mobile-flutter.md` §15 (a `client-only` mobile rebuild whose legacy app still
runs), where the flows are [Maestro](https://maestro.dev) YAML. Other target shapes keep
their AC suite in the code repo with the code it tests, and this directory stays empty.

## Why the flows live in the workbench and not in the code repo

They describe the **product** — what a user does and what must be true afterwards — which is
this repo's charter. Code repos reach them through the submodule pin they already have, and
that pin does the versioning for free: a repo checked out at `gate-4/v1` sees exactly the
flows that existed at that tag.

## Recorded against the legacy app FIRST

This is what makes the suite a characterization harness rather than a test suite that agrees
with whatever got built. Maestro drives the compiled binary through the accessibility layer,
so it is framework-agnostic: a flow recorded against the old app replays unchanged against the
rebuild, provided both expose the same selector strings. `g5-build.md`'s per-slice step 0
refuses to start a slice whose flows are missing or red against the legacy app.

A flow that genuinely cannot be recorded against the reference says so in its own header. It
is then a normal test, not parity evidence.

## The one rule with teeth

> **An assertion in a recorded flow changes only with a logged human decision.**

These files are deliberately NOT hashed into a gate — flows are recorded per slice, and
hash-locking them would mean a formal gate reopen every slice. The rule is the substitute, and
it is the same register as a reopen: a human decides, the reason is written down.

Freely allowed: new flows, new assertions, fixing a selector that never matched, deleting a
flow for a dropped feature. Needs the logged decision: **weakening or removing an assertion
that has ever been green against the legacy app.** An agent that loosens an assertion to make
a build pass has silently redefined parity, and the report still reads green.

A PreToolUse guard enforces it on any flow file git already tracks — *committed* is the line,
because recording a flow is iterative and a guard that fired through the write-run-tweak loop
would be switched off within a week. To change one deliberately:

```sh
python3 scripts/flows.py unlock --reason "..."   # logged to parity/flows/DECISIONS.md
# make the change
python3 scripts/flows.py relock
```

`--reason` is required, same as a gate reopen, and "the tests are failing" is not one — that
is the situation the rule exists for. `python3 scripts/pause_check.py` reports a workbench left unlocked
as unsafe to pause: an unlock that outlives its change is a guard that is simply off.

## Running it

```sh
maestro test parity/flows --format junit --output parity/$(date -u +%F)-ac.xml
python3 scripts/parity.py     # reads that XML and puts the AC pass rate in parity/<date>.md
```

Maestro needs macOS or Linux (WSL on Windows). Android runs headless in CI; iOS runs on
simulators only, so the iOS leg needs a Mac runner.
'''

# The budgets G0 shows the user once (05 P9). Each is read by the script that spends it; edit them here.
REBUILD_YAML = '''
# Budgets for this rebuild (05 P9). G0 shows them once; change them here, never per run.
budgets:
  parallel_lanes: 3          # build lanes open at once per slice (lane_plan.py refuses the next one)
  recorders: 4               # rspec:verify recorder agents in parallel (the skill passes it to rspec)
  hunters_per_slice: 6       # bug-hunter hunters per slice boundary (--max)
  bughunter_tokens_per_slice: 1200000  # bug-hunter --budget, in its preview units (fresh tokens): 6 hunters x B0's
                             # worst case of 100k each plus 5 verifiers x 20k. B0's processed tokens, cache reads
                             # included, ran 3-18x the preview, so expect the bill in those terms to be larger.
  fix_rounds: 2              # route.py fix rounds per slice before the user decides (as sdlc's Review)
'''

PIPELINE_YAML = '''
# Marker + metadata for orchestrator state detection. Do not edit by hand.
project: @@NAME@@
# 0.2.0 added contracts/data-model/ as a checked artifact; 0.3.0 added the architecture
# playbook (sources.yaml architecture.playbook -> adr/playbook.md, one ADR per concern in
# its concerns: map); 0.4.0 made evidence `basis` required (transcribed | observed | inferred
# on every finding's evidence entries). Scripts read this to decide whether a gap is an error
# (that version or newer) or a warning (older workbenches, which cannot be retro-enforced).
# Bump it by hand after backfilling.
schema_version: "0.4.0"
# Which major release of this plugin made the workbench. The 3.x guards and scripts act ONLY on a
# workbench that says 3 here, and refuse (or fail open) on any other, because an older workbench
# was built under different scripts, different guards and a different pipeline (1.x: PLAN.md;
# 2.x: its own mining, no rspec spec, no posture or holdout), and there is no migration between
# them. Do not edit.
rebuild_major: 3
created: @@NOW@@
'''

VALIDATE_YML = '''
name: validate-workbench
# Unfiltered on purpose: every branch and every tag gets validated, whatever the default
# branch is called. Tags matter specifically — gate.py mints gate-N/vN tags that code repos
# consume as submodule pins. If you ever add a `branches`/`branches-ignore` filter here,
# add `tags: ['**']` alongside it: a push trigger carrying only branch filters silently
# stops firing on tag pushes, which would leave those pins unvalidated.
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: python3 scripts/validate.py
'''

README = '''
# @@NAME@@ — rebuild workbench

Pipeline state store for the @@NAME@@ rebuild. Describes the product; never contains
product code. Managed by the `rebuild-pipeline` skill (product-rebuild plugin).

- `python3 scripts/preflight.py` — does the reference actually build and run? Written as
  `PREFLIGHT.md` + `preflight.json`; the last G0 action, and rspec's discovery waits
  while it reads Not-ready (`--run-build --run-tests` also executes the
  reference's own build/test commands — opt-in, they are a third party's code)
- `python3 scripts/upgrade.py` — bring the vendored `scripts/` and `schemas/` up to the installed
  plugin. Dry run by default; `--apply` copies. It refuses to overwrite any file edited
  here and shows the diff instead (`--diff <path>`), so a local change is never
  silently lost
- `python3 scripts/validate.py` — the workbench's own files: progress and sequence overlays, posture,
  the scaffold manifest in `adr/`, lock integrity. rspec's spec in `docs/` is `rspec:check`'s
- `python3 scripts/gate.py status` — pipeline/gate state
- `python3 scripts/equiv.py status` — the equivalence lane: does the rebuild produce what the OLD
  system produced? Applies under posture `observe` or `own-code` with a reference that runs;
  says so plainly otherwise (`record <feature-id>` against the legacy system,
  `replay <feature-id>` against the rebuild, `accept "<trace>" --reason` for a difference
  that is intended)
- `python3 scripts/flows.py status` — are the recorded AC flows protected? (`unlock --reason "..."`
  / `relock` around a deliberate assertion change — see `parity/flows/README.md`)
- `python3 scripts/sequence.py status` — the slice execution order, what is frozen, what is orderable
  (`init` once at G3; `reorder <Sn> --before <Sm> --reason "..."` between slices — slice ORDER
  is a logged decision here, slice BOUNDARIES are still a gate-2 reopen)
- `python3 scripts/slice_review.py <Sn>` — the between-slices standing report: does the whole product
  still run, what shipped, where that puts us, what is pressing on the plan. Advisory
- `python3 scripts/pause_check.py` — safe to stop and resume in a new session? (also reports what has
  not been pushed yet)
- `python3 scripts/autopilot.py preflight` — is this project ready to run unattended between gates?
  (`check` / `engage` / `log` / `disengage` / `status` drive a run; gates always halt for you)
- `python3 scripts/routing.py` — which model each subagent role is dispatched on, and why that rung.
  Set the ladder in `.claude/model-routing.json`: `{ "profile": "frontier" }`, or override one
  tier or role with `{ "models": { "build-lane": "opus" } }`. Absent file = the `balanced`
  default. Effort is fixed per role and not settable here — `scripts/routing.py` says why
- Decision history = `git log` on docs/, adr/, locks/

## Keep it off-machine

This workbench is the only copy of decisions that are NOT reproducible from the reference
product — the taxonomy, the ADRs, the gate history. Give it a remote early:

```sh
gh repo create @@NAME@@-workbench --private --source . --push
```

Pushing is manual. `python3 scripts/pause_check.py` tells you when something has not left the machine;
run it before you stop for the day.

After every `python3 scripts/gate.py lock <gate-id>`, push the tag too: `git push && git push --tags`.
`git push` sends no tags, and gate tags are submodule pins that code repos check out by name —
one that stays local either breaks their checkout or leaves them on the previous contract.
'''


if __name__ == "__main__":
    sys.exit(main())
