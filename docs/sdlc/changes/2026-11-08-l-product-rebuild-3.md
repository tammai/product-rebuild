# product-rebuild 3.0.0: orchestrator over rspec, sdlc and bug-hunter

## Why

**Request (verbatim, via the Orca coordinator, task pr-1):** "Implement 05-product-rebuild.md part 1 (dependencies, posture, P3 guard, refuse 2.x workbenches) in this repo through sdlc: /sdlc:start implement docs/specs/rebuild-upgrade/05-product-rebuild.md, part 1 only."

Spec: [docs/specs/rebuild-upgrade/05-product-rebuild.md](../../specs/rebuild-upgrade/05-product-rebuild.md), copied from the rebuild-upgrade spec set (sign-off D2–D5 and D7 accepted 2026-11-08). The spec is the source; this file indexes it and names the tests. Each backlog part runs as its own coordinator task; this record covers the whole spec and is refined by each part.

**Coordinator answers (2026-11-08, "all as proposed"):**
- Q1 dependency ranges, pre-release until the release task after W5 pins finals: rspec `>=0.11.0-rc.1 <1`, sdlc `>=3.5.0-rc.6 <4`, bug-hunter `>=0.4.0-rc.1 <1`; sdlc-extras kept at the sdlc range.
- Q2 `marketplace.json` allows cross-marketplace dependencies on `sdlc`, `rspec` and `bug-hunter`.
- Q3 a lane session is a call from the `lane-worker` agent (the hook payload's `agent_type`), or any call in a session whose root lies in a worktree of a repo listed in the workbench's `repos.yaml`. Everything else (the orchestrator, rspec agents) is not judged.
- Q4 denied paths: the reference checkout (`sources.yaml` `reference.checkout`, relative to the workbench, plus preflight's fallbacks that exist as git repos: `<wb>/reference`, `<wb>/../reference`, `<wb>/../<reference.name>`), and the holdout `<wb>/../<project>-holdout`, denied whether or not it exists yet. Bash is judged by every word that resolves to a path, after `cd` and `~`, and by any denied absolute path in the raw text. It is a guard, not a sandbox.
- Q5 `reference.posture`: `strict | observe | own-code`; empty means `own-code` when `reference.kind` is `own-code`, else `observe`. `validate.py` fails on any other value; `own-code` with a third-party kind is a warning.
- Q6 workbench marker `rebuild_major: 3`; a 2.x workbench is refused with a message naming product-rebuild 2.2.0. Plugin version `3.0.0-rc.1` in `plugin.json` and the CHANGELOG, no tag.
- Q7 L track, the spec's six backlog parts as `backlog.md`, branch `2026-11-08-l-product-rebuild-3` off `2026-11-08-l-shared-contracts-v1` @ 3274d37.

**Coordinator answers for part 2 (task pr-2, 2026-11-08, "all as proposed"):**
- Layout: rspec's single-repo layout at the workbench root (`docs/rspec.json`; spec and contracts in `docs/`; ADRs in `docs/decisions/`; open bundle `docs/acceptance/`). The 2.x scaffold folders stay until B6's deletions.
- Gates, names kept, order 1, 3, 2, 4, 5: gate-1 locks `features.md`, `domain.md`, `departures.yaml` and refuses before rspec stage `features-approved`; gate-3 locks `docs/decisions/` and refuses a `Proposed` ADR (the 2.x playbook-concerns check is dropped); gate-2 locks `build-plan.md` and refuses before the audit and verify summaries (verify skipped with `reference.run.kind: none`); gate-4 locks `openapi.json`, `schemas/`, `criteria.lock.json`, `acceptance/manifest.json` (the 2.x data-model check is dropped); gate-5 unchanged until B5.
- Gate 4's 90%: MVP criteria at level 2 over MVP criteria in `criteria.lock.json`; below 90% under `observe`/`own-code` it refuses unless `--accept-level2 "<reason>" --by "<name>"`, recorded in the lock; `strict` reports only.
- The skill calls rspec stages and reads rspec's `scripts/progress.py` (`$RSPEC_PLUGIN_ROOT`, else the newest installed rspec); `gate.py status` prints it, or `rspec: not run: <reason>`.
- Before `rspec:tech`, the skill writes the playbook's stack line into `docs/rspec.json` `stack` when empty (rspec weighs it as a preference).
- Slice-loop scripts still reading `plan/slices.yaml`, `matrix/` or `contracts/` change in B3/B4.

**Coordinator answers for part 3 (task pr-3, 2026-11-08, as proposed, with two additions):**
- A lane's code repo gets its criteria and open tests from `lane_plan.py`: the lane's open tests copied byte-identical (each sha256 checked against the workbench manifest) with a manifest of only those entries, and the lock copied with `spec` rewritten to the workbench submodule's `docs`, config `spec_lock` naming the copy; `lane_plan.py refresh` re-copies after `rspec:amend`. No sdlc change. Hidden tests stay out of a lane by construction.
- `holdout.py split` runs after `rspec:check` and before the gate-4 lock (a deviation from P4's "after Gate 4", which the lock record requires); gate-4 refuses until a split record matches, then records seed, count and list hash.
- Selection per D4 plus 06's flaky exclusion; the holdout is a git repo `<project>-holdout/` beside the workbench, never a submodule (refused otherwise).
- `holdout.py run`: http through `contracts.py run-http`, Playwright through the code repo's own `@playwright/test` by path (not npx), Maestro through `maestro test`, cli `not run`; reports carry criterion ID and observed behaviour only.
- Step 0 (`lane_plan.py step0`), the lane cap from `rebuild.yaml` (default 3), spec questions batched by `lane_plan.py questions`, and the flow guard over `docs/acceptance/` as proposed.

**Coordinator answers for part 4 (task pr-4, 2026-11-09):**
- Gate-1 and `departures.yaml`: P7 writes departures after Gate 1, which B2's gate-1 lock (P2's Gate 1 row) forbids. A spec change, so it went to the user with (a) recommended (gate-1 stops hashing it; the registry is append-only with its own checks). Until the user decides, B4 keeps the B2 rule and refuses a departure added after the gate-1 lock, in one place (`departures.py`).
- `route.py` as proposed; a third fix round is refused and the user decides; fix lanes through `lane_plan.py --fix`.
- `boundary.py <Sn>` sequences G6 in P6's order and itself re-runs each failing open test once (P6: "re-run the failures once"); equivalence widened from `kind: own-code` to posture `observe`/`own-code` (P3).
- Human sample as proposed: a person comparing against the running reference is the verifier (design rule 2); kept in `plan/slice-reviews/<Sn>.md`, which `slice_review.py` now carries over instead of overwriting.
- P7 readers in B4: `equiv.py accept` and `flows.py unlock --weakens` write departures; holdout, gate-5 and route.py read them.

**Coordinator answers for part 5 (task pr-5, 2026-11-09, as proposed with one change):**
- The rspec template PR: the brief forbids editing rspec, so the merged template and a PR description are written here (`docs/rspec-pr/`) and the coordinator dispatches them to the rspec worker. GP reads rspec's `docs/production-readiness.md`; gate-5 protects it instead of `parity/production-readiness.md`.
- `gp.py nfr|check` for NFR evidence; drills stay the user's.
- Gate 5 refuses on P8's list plus the readiness checklist and NFR evidence; a hidden test `not run` refuses (design rule 6); "below level 1" is level 0. Gate 1 enforces goal `production`.
- Budgets as proposed, with `bughunter_tokens_per_slice: 1200000` (6 hunters × B0's worst case of 100k each plus 5 verifiers × 20k), in bug-hunter's preview units (fresh tokens); B0's processed tokens with cache reads ran 3–18× that.
- `cost.py add` writes C7 lines per slice; P10 parking as proposed.
- The gate-1 / departures.yaml question is still with the user; `departures.gate1_allows_append` stays the single switch.

## Decisions

| Decision | Ruled out | Why |
|---|---|---|
| The P3 guard is one new PreToolUse hook, `hooks/scripts/reference_guard.py`, matcher `Read\|Grep\|Glob\|Bash`, built on `guard_io`/`hooklib` | adding the checks to `bash_guard.py` | it judges reads, not git; one guard per rule matches the other hooks |
| The guard's deny message names no path; it says lanes build from their specs and the open bundle | naming the path | P4: lane briefs never mention the holdout path, and a deny reason is read by the lane |
| A candidate reference path that is, or contains, a repo listed in `repos.yaml` is never denied | denying every fallback | `../<reference.name>` can be the rebuild's own repo when both share a name; a lane must keep its own repo |
| Posture is read by line parsing (`hooklib`, `validate.py`), like `playbook.py` and `preflight.py` read `sources.yaml` | a YAML library in the hooks | hooks import nothing outside the stdlib; same convention as the other readers |
| `REBUILD_MAJOR = 3`, `rebuild_init.py` writes `rebuild_major: 3`; the guards fail open on a 2.x workbench as they do on 1.x | migrating 2.x workbenches | D7: breaking, no migration |
| Plugin dependency ranges are pre-release (Q1) | final pins now | the dependencies are local release candidates; the release task pins them |

**Proposals not asked for:** none.

## Acceptance criteria

Part 1 (B1):

- **AC-001** 05 Decisions › Dependencies: `plugin.json` depends on rspec (`>=0.11.0-rc.1 <1`, marketplace `rspec`), bug-hunter (`>=0.4.0-rc.1 <1`, marketplace `bug-hunter`), sdlc and sdlc-extras (`>=3.5.0-rc.6 <4`, marketplace `sdlc`), version `3.0.0-rc.1`; `marketplace.json` allows the three cross-marketplace dependencies. `[manual: a configuration value; checked in review against Q1/Q2]`
- **AC-002** 05 P3, D5: Given a workbench whose `sources.yaml` sets `reference.posture` to a value other than `strict`, `observe`, `own-code` or empty, when `validate.py` runs, then it fails naming the field; with `posture: own-code` and `kind: third-party` it warns.
- **AC-003** 05 P3: Given posture `observe` or `strict` (or empty with a third-party kind), when the `lane-worker` agent calls Read, Grep, Glob or Bash on a path inside the reference checkout, then the guard denies it; the same calls from a session that is not a lane (the orchestrator) are allowed.
- **AC-004** 05 P3, P4: Given any posture, `own-code` included, when a lane (the `lane-worker` agent, or a session rooted in a lane worktree of a listed repo) reads inside `<project>-holdout` beside the workbench, then the guard denies it; under `own-code` (explicit, or empty with `kind: own-code`) the same lane may read the reference checkout.
- **AC-005** 05 D7: Given a workbench marked `rebuild_major: 2`, when `upgrade.py` runs, then it refuses with a message naming product-rebuild 2.2.0 (with `--auto`: one line, exit 0); a new workbench is marked `rebuild_major: 3`.

Later parts (refined when each part starts):

- **AC-006** 05 P2 (B2): Given a workbench holding the rspec spec in `docs/` (rspec single-repo layout), when `gate.py` runs, then the gates go in rspec's order 1, 3, 2, 4, 5 and lock rspec's artifacts: gate-1 `features.md`, `domain.md`, `departures.yaml` (refused before rspec's stage `features-approved`); gate-3 `docs/decisions/` (refused while an ADR is `Proposed`); gate-2 `build-plan.md` (refused before the audit summary and the verify summary, or `reference.run.kind: none`); gate-4 `openapi.json`, `schemas/`, `criteria.lock.json`, `acceptance/manifest.json`.
- **AC-012** 05 P2 Gate 4 (B2): Given MVP criteria in `criteria.lock.json` below 90% at level 2, when `gate.py lock gate-4` runs under posture `observe` or `own-code`, then it refuses unless given `--accept-level2 "<reason>" --by "<name>"`, which records share, reason and signer in the lock; under `strict` the share is reported, never refused.
- **AC-013** 05 P2, design rule 6 (B2): `gate.py status` prints rspec's stage, next step and pending units from rspec's own `progress.py`, or `rspec: not run: <reason>` when rspec cannot be found.
- **AC-014** 05 P2 (B2): the skill routes each phase to rspec's stages (`rspec:init` … `rspec:handoff`) and to this repo's gates in P2's order, never re-implementing a stage; before `rspec:tech` it writes the playbook's stack line into `docs/rspec.json` `stack` when that is empty. `[manual: skill prose, checked in review]`
- **AC-007** 05 P4, D4 (B3): Given a workbench after `rspec:check`, when `holdout.py split` runs, then per slice of `build-plan.md` it hides ceil(25%) of the level 2 tests, at least one per feature with ≥ 3 criteria, the same seed giving the same list; the hidden files move to the git repo `<project>-holdout/` beside the workbench and their manifest entries say `visibility: hidden`; it refuses when a listed code repo contains or references that repo. `gate.py lock gate-4` refuses until the split record matches the manifest, then records seed, count and list hash.
- **AC-015** 05 P4 (B3): Given hidden tests, when `holdout.py run <Sn>` runs against a build, then it reports each criterion pass, fail or not run, and a failure carries only the observed behaviour, never the expected value or the test's text.
- **AC-008** 05 P5 (B3): Given a committed file under the workbench's `docs/acceptance/`, when a tool edits it, then the flow guard blocks it until `flows.py unlock --acceptance --reason` is active.
- **AC-016** 05 P5 step 2 (B3): Given a slice's lane, when `lane_plan.py <Sn> <lane> --features …` opens it, then its change file cites the criterion IDs (`- **AC-001** → F-…`), sdlc's state gets them as `--criteria`, the lane worktree gets only its open tests (byte-identical, sha256 checked against the workbench manifest) with a manifest of those entries, and a lock copy whose `spec` points into the workbench submodule with config `spec_lock` naming it; it refuses a lane beyond the slice's lane cap (`rebuild.yaml` `budgets.parallel_lanes`, default 3).
- **AC-017** 05 P5 step 0 (B3): Given a slice with a criterion that has neither a level 2 test nor an rspec verify reason, when `lane_plan.py step0 <Sn>` runs, then it names the criterion and the `rspec:verify --only <features>` to run, and `lane_plan.py` refuses to open the slice's lanes.
- **AC-018** 05 P5 step 3 (B3): Given spec questions in the lanes' `.sdlc/.work/spec-questions/`, when `lane_plan.py questions <Sn>` runs, then they are batched into `plan/spec-questions/<Sn>.md`; `lane_plan.py refresh <Sn> <lane>` re-copies the lock and open tests after an `rspec:amend`.
- **AC-009** 05 P6 routing (B4): Given a slice's findings, when `route.py <Sn>` runs, then each reproduced finding goes where contracts C6 routes its class (build-defect and test-defect to one sdlc fix lane per feature, spec-gap to `rspec:amend`, reference-defect to the user, flaky and environment to the orchestrator), an `accepted-departure` or a finding a decided departure explains is dropped, an unreproduced one is not routed, and a third round is refused: the user decides.
- **AC-019** 05 P6 sequence (B4): Given a slice build, when `boundary.py <Sn>` runs, then it re-runs each failing open test once (a pass on the re-run is flaky, not a finding), writes a reproduced finding for each that still fails, and stops before the hidden suite while a build-defect or spec-gap is open; once they are closed it runs the hidden suite, prints the bug-hunter command, and passes only when the open and hidden suites are green or explained, no high finding is open, bug-hunter has run and the human sample is recorded.
- **AC-020** 05 P6 step 6 (B4): `boundary.py sample <Sn>` picks 2–3 of the slice's features from a recorded seed, weighted to criteria below level 2, into `plan/slice-reviews/<Sn>.md`; each `differs` line becomes a reproduced finding with the reviewer as verifier.
- **AC-021** 05 P7 (B4): `departures.yaml` explains differences everywhere: a hidden failure a decided departure names is `explained`; `equiv.py accept` and `flows.py unlock --weakens` write departures (no more DECISIONS.md for accepted differences); gate-5 refuses only on a red trace no departure explains. While gate-1 hashes `departures.yaml`, a departure added after its lock is refused with nothing written (pending the user's decision on the gate-1 row).
- **AC-022** 05 P6 routing (B4): `lane_plan.py <Sn> <lane> --fix <round> --findings <ids>` opens a fix lane whose ACs cite each finding's criterion (or restate what the build did when it has none), refusing a finding the round did not route to sdlc.
- **AC-010** 05 P8 (B5): Given a workbench otherwise ready, when `gate.py lock gate-5` checks it, then it refuses on each of: an unchecked item in rspec's `production-readiness.md`; an NFR without evidence; a hidden test that failed or did not run; a red equivalence trace no departure explains; an open high finding; a `proposed` departure; an MVP criterion below level 1. Gate 1 refuses a rebuild whose `docs/rspec.json` goal is not `production`.
- **AC-023** 05 P8 (B5): `gp.py nfr` lists every NFR with its own Verification in `parity/gp/nfr-evidence.md`, keeping filled rows; `gp.py check` fails on any row without evidence and a pass or `n/a: <reason>`, and on a drill without the person who performed it.
- **AC-024** 05 P9 (B5): a new workbench has `rebuild.yaml` budgets (parallel lanes 3, recorders 4, hunters per slice 6, bug-hunter tokens per slice 1,200,000, fix rounds 2), and the scripts that spend them read them: the lane cap, `route.py`'s round cap, and the bug-hunter command `boundary.py` prints (`--max`, `--budget`, `--cost-log logs/<Sn>/cost.jsonl`).
- **AC-025** 05 P9 (B5): `cost.py add` appends a contracts C7 line to `logs/<Sn>/cost.jsonl`, and `boundary.py` prints the slice's cost by stage beside its quality figures (`not run: no cost log` without one).
- **AC-026** 05 P10 (B5): `autopilot.py park` records a decision autopilot may not take, and `autopilot.py blocked <target>` says whether a gate, boundary or slice's lanes depend on a parked one: a parked human sample of S1 blocks S1's boundary and Gate 5, not S2's lanes.
- **AC-027** 05 P8 (B5): GP's own checklist items are merged into rspec's production-readiness template as a PR proposal in `docs/rspec-pr/` (the rspec repo is not edited here). `[manual: a document for the rspec worker, checked in review]`
- **AC-011** 05 P1 (B6): `docs/MIGRATION-3.md` maps every 2.x capability to its 3.0 owner with a passing test or fixture, before any deletion.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | manual | configuration values in plugin.json and marketplace.json, checked in review against Q1/Q2 |
| AC-002 | skills/rebuild-pipeline/eval/reference_guard.py › posture | `python3 skills/rebuild-pipeline/eval/reference_guard.py posture` |
| AC-003 | skills/rebuild-pipeline/eval/reference_guard.py › reference | `python3 skills/rebuild-pipeline/eval/reference_guard.py reference` |
| AC-004 | skills/rebuild-pipeline/eval/reference_guard.py › holdout | `python3 skills/rebuild-pipeline/eval/reference_guard.py holdout` |
| AC-005 | skills/rebuild-pipeline/eval/v0_fence.py | `python3 skills/rebuild-pipeline/eval/v0_fence.py` |
| AC-006 | skills/rebuild-pipeline/eval/gates_rspec.py › order | `python3 skills/rebuild-pipeline/eval/gates_rspec.py order` |
| AC-012 | skills/rebuild-pipeline/eval/gates_rspec.py › level2 | `python3 skills/rebuild-pipeline/eval/gates_rspec.py level2` |
| AC-013 | skills/rebuild-pipeline/eval/gates_rspec.py › progress | `python3 skills/rebuild-pipeline/eval/gates_rspec.py progress` |
| AC-014 | manual | skill prose (SKILL.md phase routing, stack preference step), checked in review |
| AC-007 | skills/rebuild-pipeline/eval/holdout_eval.py › split | `python3 skills/rebuild-pipeline/eval/holdout_eval.py split` |
| AC-015 | skills/rebuild-pipeline/eval/holdout_eval.py › run | `python3 skills/rebuild-pipeline/eval/holdout_eval.py run` |
| AC-008 | skills/rebuild-pipeline/eval/lanes_rspec.py › flows | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py flows` |
| AC-016 | skills/rebuild-pipeline/eval/lanes_rspec.py › lane | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py lane` |
| AC-017 | skills/rebuild-pipeline/eval/lanes_rspec.py › step0 | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py step0` |
| AC-018 | skills/rebuild-pipeline/eval/lanes_rspec.py › questions | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py questions` |
| AC-009 | skills/rebuild-pipeline/eval/g6_eval.py › route | `python3 skills/rebuild-pipeline/eval/g6_eval.py route` |
| AC-019 | skills/rebuild-pipeline/eval/g6_eval.py › boundary | `python3 skills/rebuild-pipeline/eval/g6_eval.py boundary` |
| AC-020 | skills/rebuild-pipeline/eval/g6_eval.py › sample | `python3 skills/rebuild-pipeline/eval/g6_eval.py sample` |
| AC-021 | skills/rebuild-pipeline/eval/g6_eval.py › departures | `python3 skills/rebuild-pipeline/eval/g6_eval.py departures` |
| AC-022 | skills/rebuild-pipeline/eval/g6_eval.py › fix | `python3 skills/rebuild-pipeline/eval/g6_eval.py fix` |
| AC-010 | skills/rebuild-pipeline/eval/gp_eval.py › gate5 | `python3 skills/rebuild-pipeline/eval/gp_eval.py gate5` |
| AC-023 | skills/rebuild-pipeline/eval/gp_eval.py › nfr | `python3 skills/rebuild-pipeline/eval/gp_eval.py nfr` |
| AC-024 | skills/rebuild-pipeline/eval/gp_eval.py › budgets | `python3 skills/rebuild-pipeline/eval/gp_eval.py budgets` |
| AC-025 | skills/rebuild-pipeline/eval/gp_eval.py › cost | `python3 skills/rebuild-pipeline/eval/gp_eval.py cost` |
| AC-026 | skills/rebuild-pipeline/eval/gp_eval.py › park | `python3 skills/rebuild-pipeline/eval/gp_eval.py park` |
| AC-027 | manual | the merged template and PR description in docs/rspec-pr/, checked in review |
| AC-011 | skills/rebuild-pipeline/eval/migration_3.py (B6) | `python3 skills/rebuild-pipeline/eval/migration_3.py` |

## Must never break

- Every guard fails open outside a 3.x workbench and fails closed (blocks) on a crash inside a pipeline session, as the existing guards do.
- The orchestrator and the spec side keep reading the reference under `observe` and `own-code`; only lanes are judged.
- A lane can always read and write its own worktree and repo.
- Scripts stay stdlib only; a vendored workbench script runs alone.

## Failure modes

- Untrusted input reaching a file path: the guard reads paths from tool calls a lane makes; a path it cannot resolve (`cd $X`) is judged by its absolute words and the raw-text check, and a crash blocks → AC-003, AC-004.
- A CRLF `sources.yaml` or `pipeline.yaml` (Windows checkout): every reader normalises line ends → AC-002.

## Out of scope

- Parts 2–6 (each its own task); the end-to-end runs in 06-rollout.md (W5); final dependency pins and the release.
- A sandbox: the guard does not stop a lane that computes a path at run time; the README says so.
