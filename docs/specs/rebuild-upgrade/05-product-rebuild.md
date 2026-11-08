# Spec: product-rebuild 3.0.0, orchestrator over rspec, sdlc and bug-hunter

2026-11-08 · @Tam Mai · draft for sign-off · depends on contracts v1, rspec 0.11, sdlc 3.5, bug-hunter 0.4

## Problem

product-rebuild 2.2 wraps sdlc for the build but still mines the reference itself (G1–G4b), duplicating what rspec now does better: stories with evidence, `domain.md`, OpenAPI/JSON Schema contracts, a three-agent audit, and from 0.11 recorded tests. Its strongest checks are narrow:

- Record-first flows with the assertion guard apply only to `mobile-flutter` `client-only`. On a web/API rebuild, G6's AC suite is the tests the sdlc lanes wrote, which `g6-parity.md` itself calls evidence of nothing.
- The equivalence lane runs only for `own-code` references.
- No hidden tests; builders see every test that judges them.
- No search for unknown defects; every check confirms known expectations.
- Accepted differences live in four places.
- No human comparison against the reference before Gate 5.

## Decisions

| Question | Decision |
|---|---|
| Shape | product-rebuild is an orchestrator. rspec owns the spec and its verification, sdlc owns the build, bug-hunter owns defect search. This repo owns: G0, preflight, gates and locks, hidden tests, slice loop, G6, routing, GP. Nothing from the three plugins is copied. |
| Dependencies | `plugin.json` adds `rspec` (`>=0.11 <1`, marketplace `rspec`) and `bug-hunter` (`>=0.4 <1`, marketplace `bug-hunter`) next to sdlc `>=3.5 <4`; `marketplace.json` allows the three cross-marketplace dependencies. |
| Mining **(sign-off D3)** | G1–G4b are replaced by rspec stages. Agents `miner`, `spec-writer`, `data-model-drafter`, `adr-drafter`, `rubric-judge` and their references and scripts are deleted after the capability check in P1. |
| Rule Cards **(sign-off D2)** | Retired. Their content maps to `domain.md` rules and criteria tagged `[code]` with `repo@commit path:line`. The `rules-recall` eval fixture is ported to rspec as a recall test for OSS-mode discovery. |
| Posture **(sign-off D5)** | `sources.yaml` → `reference.posture`: `strict` · `observe` (default for third-party) · `own-code`. See P3. |
| Hidden share **(sign-off D4)** | 25% of level 2 tests per slice, stratified by feature, at least 1 per feature with ≥ 3 criteria, fixed seed recorded at the lock. |
| Migration **(sign-off D7)** | Breaking. 3.0 refuses a 2.x workbench with a message naming the last 2.x release; finish those rebuilds on 2.2. |

## Requirements

### P1 Capability check before deletion

Before deleting any 2.x part, a table in `docs/MIGRATION-3.md` maps each 2.x capability to its 3.0 owner (rspec stage, sdlc feature, bug-hunter flag, or this repo) with a test or fixture that proves it there. Anything without an owner stays or blocks the release. Known items to place: changelog lane A and the 30-day upstream re-mine, NFR lane, UX flows lane, ERD gate, `basis` evidence, untrusted-source hardening, playbook ADR defaults, build runbook.

### P2 Pipeline and gates

| Step | Owner | Gate (hash-locked by `gate.py`) |
|---|---|---|
| G0 reference, posture, playbook, budgets | this repo | — |
| Preflight: reference builds, runs, seeds | this repo (unchanged) | blocks while `Not-ready` |
| init → discover → features | rspec | **Gate 1**: `features.md`, `domain.md`, `departures.yaml` |
| stories → tech (playbook answers passed as stack preferences) | rspec | **Gate 3**: accepted ADRs (rspec handoff step 1) |
| audit → verify | rspec | checked at Gate 4 |
| handoff (build plan, ≤ 10 criteria per slice) | rspec | **Gate 2**: slice boundaries |
| contracts and tests | rspec output | **Gate 4**: `openapi.json`, `schemas/`, `criteria.lock.json`, `acceptance/manifest.json`; refuses MVP level 2 < 90% for `observe`/`own-code` unless the user signs a reason |
| hidden split (P4), slice loop (P5–P6) | this repo + sdlc | per-slice boundary (advisory) |
| GP | this repo | **Gate 5** |

Gate names keep their 2.x numbers so existing locks, tags and docs stay readable; their order now follows rspec (architecture before slicing).

The workbench holds the rspec spec (rspec single-repo layout) and the open bundle. Code repos pin the workbench as today. rspec runs inside the workbench; this repo's skill calls `rspec:<stage>` and reads `progress.py` for state, never re-implementing stages.

### P3 Posture

| | strict | observe | own-code |
|---|---|---|---|
| Spec side reads reference code | no | yes (rspec OSS mode) | yes |
| Spec side observes and records behaviour | yes | yes | yes |
| Builder lanes may read reference code or raw responses | no | no | yes |
| Equivalence (traffic replay) | no | yes, on the local reference | yes |

Builder isolation is enforced by a PreToolUse guard in lane sessions denying Read/Grep/Glob/Bash on the reference checkout path and the holdout path. It is a guard, not a sandbox; the README says so. Legal fit of a posture to a licence is the user's call; G0 shows the licence and asks.

### P4 Hidden tests

- `holdout.py split` after Gate 4: selects hidden tests per D4, moves them to a sibling repo `<name>-holdout/` that is never a submodule of any code repo, marks them `visibility: hidden` in the workbench manifest, records seed and list hash in the Gate 4 lock.
- Lane briefs never mention the holdout path; the P3 guard denies it.
- `holdout.py run <slice>` runs them against the slice build at G6. Results are reported per criterion, never with test content, so a failure report does not leak the test into a lane: the lane gets the criterion ID and the observed behaviour.

### P5 Slice loop

1. **Step 0**: every criterion of the slice has a level 2 test or a recorded reason (`unrecordable`, `read-only reference`). Missing → `rspec:verify --only <features>`.
2. **Lanes**: `lane_plan.py` passes each lane its criterion IDs and the open bundle; sdlc runs spec-backed mode (sdlc S2, S3). Lane cap from G0 budgets (default 3 parallel).
3. **Spec questions** (sdlc S10): the orchestrator collects `.sdlc/.work/spec-questions/*.json`, batches them per slice, runs `rspec:amend` (human approval when the change touches an MVP criterion's `then`), re-verifies, unblocks the parts.
4. The flow guard (`flows_guard.py`) generalises from `parity/flows/` to the workbench `acceptance/` folder; `flows.py unlock --reason` stays the only edit path.

### P6 G6, cheapest first

Runs at each slice boundary from `boundary.py`. Each step runs only when the previous ones left no `build-defect` or `spec-gap` open; findings are batched into one fix round per class.

1. **Open suite**: already run by the lanes; read their JUnit, re-run the failures once (flaky rules unchanged).
2. **Hidden suite**: `holdout.py run`. Target: 100% pass, or each failure explained by a departure.
3. **Equivalence**: when posture allows and `reference.run` is local; recorded traffic of this slice's operations replayed against the build, diffs filtered by `departures.yaml` `match` rules.
4. **Coverage and regression**: `parity.py` and `slice_review.py`, unchanged in purpose.
5. **bug-hunter**: `bug-hunter:hunt --oracle <workbench spec> --target rebuild --reference reference --format finding-v1 --out parity/findings/<Sn>/ --yes --budget <slice budget>`. Browser mode when the code repo has Playwright.
6. **Human sample**: `boundary.py sample` picks 2–3 features of the slice (fixed seed, weighted to level < 2 criteria); the user compares them against the reference and records `agree` / `differs: <what>` in `plan/slice-reviews/<Sn>.md`. A difference becomes a finding. Autopilot parks this step; the boundary stays open until a human records it.

Routing (`route.py`, by `finding-v1.class`): `build-defect`, `test-defect` → a fix lane in sdlc (one feature per slice per round, findings as ACs) · `spec-gap` → `rspec:amend`, then re-verify, then a fix lane · `reference-defect` → human: copy it or add a departure · `flaky`, `environment` → orchestrator fixes the harness. Round cap 2, then the user decides, as in sdlc Review.

Boundary passes when: open and hidden suites green or explained; no open `high` finding; the human sample recorded.

### P7 One departures registry

`departures.yaml` in the workbench (contracts C5) replaces G3 `departures:`, `parity/flows/DECISIONS.md` and `parity/equiv/DECISIONS.md`. `parity.py`, `equiv.py`, `holdout.py`, `route.py`, Gate 5 and bug-hunter read it. `flows.py unlock` writes its reason as a departure when the change weakens an assertion.

### P8 GP and Gate 5

- One checklist: rspec's `production-readiness.md` (goal `production` is forced in a rebuild). GP's own list merges into rspec's template (PR to rspec), so there is one source.
- GP adds execution: each NFR's stated verification is run against the production candidate (load test, backup restore, failover drill as the NFR says) with evidence linked. Drills stay the user's to perform.
- Gate 5 refuses while: any hidden test fails without a departure; any equivalence trace is red without a departure; any `high` finding is open; any departure is `proposed`; any MVP criterion is below level 1.

### P9 Budgets and logs

G0 asks once for budgets (defaults shown, editable in `rebuild.yaml`): parallel lanes 3, recorders 4, hunters per slice 6, bug-hunter tokens per slice, fix rounds 2. Every orchestrated plugin run passes `--cost-log` or writes `cost.jsonl` to `<workbench>/logs/`. `boundary.py` prints the slice's cost by stage beside its quality figures.

### P10 Autopilot

Inherits rspec's autopilot rules for features and ADRs and sdlc's for lanes. Never automatic: Gate 1 feature approval when a used feature would be dropped, departures, the human sample, production deploy, Gate 5. Each parked item blocks only what depends on it; the rest of the slice continues.

## Backlog parts

1. Dependencies, posture field, P3 guard, refusal of 2.x workbenches.
2. P2 wiring: skill calls rspec stages, gate locks on rspec artifacts, `progress.py` integration.
3. P4 holdout; P5 slice loop changes, generalised flow guard.
4. P6 G6 sequence, `route.py`, human sample; P7 registry migration in scripts.
5. P8 GP changes (and the rspec template PR); P9; P10.
6. P1 capability table, then deletions; docs (README, PLAYBOOK, pipeline image).

## Acceptance

- `docs/MIGRATION-3.md` complete, every row with a passing test or fixture.
- Unit tests: holdout selection (stratification, minimums, seed reproducibility, no hidden path in any code repo), routing table, Gate 5 refusal conditions, departures matching in parity and equivalence.
- Guard test: a lane session cannot read the holdout or reference path through Read, Grep, Glob or Bash.
- End-to-end run in [06-rollout.md](06-rollout.md) passes.
