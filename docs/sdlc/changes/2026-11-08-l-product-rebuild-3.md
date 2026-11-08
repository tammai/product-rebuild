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
- **AC-007** 05 P4, D4 (B3): `holdout.py split` selects 25% of level 2 tests per slice, stratified by feature, at least 1 per feature with ≥ 3 criteria, reproducible from the recorded seed, and no hidden path lands in a code repo; `holdout.py run` reports per criterion without test content.
- **AC-008** 05 P5 (B3): the flow guard protects the workbench `acceptance/` folder; `flows.py unlock --reason` stays the only edit path.
- **AC-009** 05 P6, P7 (B4): `route.py` routes each `finding-v1.class` as P6's table says; parity and equivalence diffs matched by a `departures.yaml` `match` rule are not failures.
- **AC-010** 05 P8–P10 (B5): Gate 5 refuses on each P8 condition; budgets and cost logs per P9.
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
| AC-007 | skills/rebuild-pipeline/eval/holdout.py (B3) | `python3 skills/rebuild-pipeline/eval/holdout.py` |
| AC-008 | skills/rebuild-pipeline/eval/flows_acceptance.py (B3) | `python3 skills/rebuild-pipeline/eval/flows_acceptance.py` |
| AC-009 | skills/rebuild-pipeline/eval/route.py (B4) | `python3 skills/rebuild-pipeline/eval/route.py` |
| AC-010 | skills/rebuild-pipeline/eval/gate5.py (B5) | `python3 skills/rebuild-pipeline/eval/gate5.py` |
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
