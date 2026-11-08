# Migrating to product-rebuild 3.0

product-rebuild 3.0 is an orchestrator over three plugins: **rspec** writes and verifies the spec, **sdlc**
builds each lane, **bug-hunter** searches for defects. This repo keeps G0, preflight, the gates and their locks,
the hidden tests, the slice loop, G6, routing and GP ([spec 05](specs/rebuild-upgrade/05-product-rebuild.md)).

There is no migration of a running rebuild (sign-off D7). 3.0 refuses a workbench 2.x made, with a message
naming product-rebuild 2.2.0; finish that rebuild on 2.2.0 (with sdlc 3.3), or start a new workbench on 3.0.

## Where each 2.x capability went

05 P1: before a 2.x part was deleted, each capability it carried was given a 3.0 owner and a test that passes
there. `skills/rebuild-pipeline/eval/migration_3.py` reads this table and runs every proof this repo owns
(`eval/<file>.py [group]`); with `--external` and `RSPEC_PLUGIN_ROOT`, `SDLC_PLUGIN_ROOT`,
`BUGHUNTER_PLUGIN_ROOT` pointing at checkouts, it also runs each cited rspec, sdlc and bug-hunter test from a copy
at the cited commit. A row that is not fully placed says so in Status.

| # | 2.x capability | 3.0 owner | Proof | Status |
|---|---|---|---|---|
| 1 | G0: reference choice, licence posture | this repo (G0), plus `reference.posture` (strict, observe, own-code) | `eval/reference_guard.py posture` | moved |
| 2 | Preflight: the reference is at the pinned commit and runs; G0 holds discovery until it does | this repo, unchanged | `eval/gate_status.py` | kept |
| 3 | G1 lane D, ground truth from the reference's code (schema, routes, permissions, jobs) at a pinned commit | rspec discover in OSS mode: `[code]` evidence cites `repo@commit path:line` | `rspec@20bd8ee2eeb4 tests/test_oss.py::test_reading_oss_code_requires_a_pinned_commit` | moved |
| 4 | G1 lane A, features from docs and changelog | rspec discover and features; the features coverage pass builds its reference list from the docs and 12 months of changelog | `rspec@20bd8ee2eeb4 tests/test_progress.py::test_discover_resumes_only_unfinished_modules` · `rspec@20bd8ee2eeb4 tests/test_triage.py::test_a_drop_feature_promoted_after_handoff_routes_to_triage` | moved |
| 5 | The 30-day upstream re-mine of the changelog | this repo: `boundary.py` says when it is due and names the rspec work (rerun the features coverage pass, triage) | `eval/g6_eval.py remine` | kept |
| 6 | G1 NFR lane | rspec tech `nfr.md`, each NFR with its verification; GP runs the verification | `rspec@20bd8ee2eeb4 tests/test_production.py::test_production_nfr_without_verification_fails` · `eval/gp_eval.py nfr` | moved |
| 7 | G1 UX flows lane and record-first flows: tests recorded against the reference before the build | rspec discover (`screens.md`) and verify (recorded tests, three greens to level 2); sdlc runs the recorded rows, Maestro included | `rspec@20bd8ee2eeb4 tests/test_verify.py::test_three_greens_reach_level_2` · `sdlc@fdda00530ff1 tests/test_recorded_tests.py::test_a_maestro_row_runs_maestro_and_is_not_run_without_it` | moved |
| 8 | Lane R Rule Cards: one cited business rule per card, checked against the build (D2) | rspec `domain.md` (permissions, value sets, limits) and criteria tagged `[code]` | `rspec@20bd8ee2eeb4 tests/test_domain.py::test_operation_roles_differing_from_the_permission_table_are_an_error` · `rspec@20bd8ee2eeb4 tests/test_quality_bar.py::test_criteria_without_a_source_tag_fail` | moved |
| 9 | The `rules-recall` eval: how much of a known rule set discovery finds | rspec, as a recall test for OSS-mode discovery: the fixture and the proposal are in `docs/rspec-pr/rules-recall/` for the rspec worker | `fixture docs/rspec-pr/rules-recall/gold.yaml` | proposed; blocks 3.0.0 until rspec merges it |
| 10 | `basis` evidence (transcribed, observed, inferred) and the parity report's inferred-only features | rspec source tags on every criterion, and criterion levels (0 to 2) raised only by the audit and recorded tests | `rspec@20bd8ee2eeb4 tests/test_quality_bar.py::test_criteria_without_a_source_tag_fail` · `rspec@20bd8ee2eeb4 tests/test_audit.py::test_audit_verdicts_raise_criteria_to_level_1` · `eval/contracts_v1.py` | moved |
| 11 | Untrusted-source hardening: briefs treat reference content as data; the injection scan, gate and canary | this repo's hooks, unchanged; rspec's agents treat web pages and the product as data | `eval/lane_guards.py injection` | kept |
| 12 | G2 feature matrix and Gate 1 (taxonomy lock) | rspec features (`features.md`, `domain.md`, `departures.yaml`); gate-1 locks them | `rspec@20bd8ee2eeb4 tests/test_departures.py::test_drop_row_links_a_departure` · `eval/gates_rspec.py order` | moved |
| 13 | G3 slicing and Gate 2 (slice-plan lock) | rspec handoff (`build-plan.md`, at most 10 criteria a slice); gate-2 locks it | `rspec@20bd8ee2eeb4 tests/test_build_plan_criteria.py::test_slice_lists_its_criterion_ids` · `rspec@20bd8ee2eeb4 tests/test_check_spec.py::test_sdlc_slice_over_ten_criteria_warns` · `eval/gates_rspec.py order` | moved |
| 14 | Slice order as a logged decision (`sequence.py reorder`) | this repo, over rspec's slices; a slice's dependencies come from its stories | `eval/coverage_rspec.py order` | kept |
| 15 | G4a ADRs drafted per concern (adr-drafter) and Gate 3 | rspec tech ADRs, approved in rspec handoff; gate-3 refuses a `Proposed` ADR | `rspec@20bd8ee2eeb4 tests/test_check_spec.py::test_handoff_requires_every_mvp_in_build_plan_and_no_proposed_adr` · `eval/gates_rspec.py order` | moved |
| 16 | Playbook ADR defaults and scaffold manifests, vendored and locked at Gate 3 | the playbook's stack line goes to rspec tech as `stack`; `playbook.py vendor` copies the playbook and its scaffold manifest to `adr/`, which gate-3 locks with rspec's ADRs | `rspec@20bd8ee2eeb4 tests/test_check_spec.py::test_handoff_with_no_recorded_stack_warns` · `eval/gates_rspec.py scaffold` · `eval/scaffold_repo.py` | moved |
| 17 | G4b data model and the ERD gate (data-model-drafter, `erd.py`) | rspec tech data model and entity schemas, checked against `domain.md`; gate-4 locks `schemas/` | `rspec@20bd8ee2eeb4 tests/test_domain.py::test_a_body_field_missing_from_its_entity_schema_is_an_error` · `eval/gates_rspec.py order` | moved |
| 18 | G4b contracts and their `$ref` checks, Gate 4 | rspec tech `openapi.json` and its reference checks; gate-4 locks it with the lock and the bundle | `rspec@20bd8ee2eeb4 tests/test_contract_refs.py::test_a_ref_to_a_missing_schema_is_an_error` · `eval/gates_rspec.py level2` | moved |
| 19 | `target_shape: client-only`: transcribe the existing API, inventory what the old app left on devices | rspec's modernize track (data migration, cutover) covers part of it; the API transcription and device inventory have no rspec test | `rspec@20bd8ee2eeb4 tests/test_modernize.py::test_modernize_spec_with_migration_and_cutover_passes` | partial: the coordinator puts "blocks 3.0.0 or known gap" to the user at release |
| 20 | Module specs with acceptance criteria per slice (spec-writer, `rules_for.py`, `lane_plan.py --specs`) | rspec stories (criteria with IDs); sdlc spec-backed lanes cite them; `lane_plan.py --features` opens each lane | `rspec@20bd8ee2eeb4 tests/test_criteria_ids.py::test_story_breaking_c1_or_c2_fails` · `sdlc@fdda00530ff1 tests/test_spec_backed.py::test_every_slice_criterion_is_cited_or_set_aside` · `eval/lanes_rspec.py lane` | moved |
| 21 | A lane's `amend:` question on a wrong spec | sdlc spec questions, batched by `lane_plan.py questions`, answered by `rspec:amend` | `sdlc@fdda00530ff1 tests/test_spec_backed.py::test_a_spec_question_is_a_finding_and_blocks_the_part` · `eval/lanes_rspec.py questions` | moved |
| 22 | The rubric judge at each gate (rubric-judge, `cite_excerpts.py`, `gate_facts.py`, `evidence_bundle.py`) | rspec audit: three fresh auditors (facts, coverage, consistency) before handoff | `rspec@20bd8ee2eeb4 tests/test_audit.py::test_after_tech_the_pipeline_audits_before_handoff` | moved |
| 23 | Model routing per role | this repo, for the build lane and sdlc's lane reviews; rspec routes its own agents | `eval/lane_plan.py routing` | kept |
| 24 | The lane worker's standing rules (test cadence, long runs, migrations, helpers) | this repo, `agents/lane-worker.md` | `eval/lane_plan.py worker` | kept |
| 25 | Archiving a shipped lane; the slice review naming a lane that rewrote its criteria | this repo | `eval/lanes_rspec.py archive` | kept |
| 26 | Recorded flows read-only; loosening one is a logged unlock | this repo's flow guard, over rspec's `docs/acceptance/` | `eval/lanes_rspec.py flows` | moved |
| 27 | Equivalence: replaying recorded traffic against the build | this repo, for posture `observe` and `own-code` (2.x: own-code only); accepted differences are departures | `eval/g6_eval.py departures` | kept |
| 28 | The AC suite read from JUnit, a rerun counted once, local-calendar dates | this repo | `eval/dates_and_reruns.py` | kept |
| 29 | Parity coverage and the slice review | this repo, over rspec's `features.md` and `build-plan.md` | `eval/coverage_rspec.py reports` · `eval/coverage_rspec.py notrun` | moved |
| 30 | Accepted differences in G3 `departures:`, `parity/flows/DECISIONS.md` and `parity/equiv/DECISIONS.md` | one registry, `docs/departures.yaml` (contracts C5), read by this repo and bug-hunter | `eval/g6_eval.py departures` · `bug-hunter@36f43717b504 tests/test_departures.py::test_registry_is_read_and_checked` | moved |
| 31 | The build runbook S1 writes, required before later slices touch code | this repo, `runbook_guard.py` | `eval/lane_guards.py runbook` | kept |
| 32 | The code-repo guards (bash guard, spec gate, commit gates) | this repo, unchanged | `eval/lane_guards.py specgate` · `eval/lane_guards.py commit` | kept |
| 33 | Lane supervision: one tracked process per joint run, a dead driver named | this repo | `eval/run_supervision.py phases` | kept, except the baselined stall checks |
| 34 | The pause check and the code-repo marker | this repo | `eval/run_supervision.py markers` | kept |
| 35 | Gate locks, tags and the gate guard | this repo, on rspec's artifacts in rspec's order | `eval/gates_rspec.py order` | moved |
| 36 | GP and Gate 5 | rspec's `production-readiness.md` (goal `production`); this repo runs each NFR's verification and refuses Gate 5 | `rspec@20bd8ee2eeb4 tests/test_production.py::test_pipeline_is_not_done_until_readiness_items_are_done` · `eval/gp_eval.py gate5` | moved |
| 37 | Autopilot halting at decisions it may not take | this repo: it parks them and blocks only what depends on them | `eval/gp_eval.py park` | moved |
| 38 | Workbench tooling upgrades, and refusing a workbench another major made | this repo | `eval/v0_fence.py` | kept |
| 39 | Code repos created from the playbook's scaffold manifest | this repo, `scaffold-repo` | `eval/scaffold_repo.py` | kept |

## Known limits of the reference guard

The guard that keeps lanes out of the reference and the hidden tests is a guard, not a sandbox (P3). It judges
the paths a call spells. It does not see a path computed at run time (`$X`, `$(…)`, `%LOCALAPPDATA%`), a script
or interpreter that opens the file itself, a recursive reader or writer it does not list, a nested shell
(`bash -c`, `cmd /c`, `powershell -c` with the path built inside), or a Windows short name (`PRODUCT~1`). The
list is not grown further. The hidden tests now live in a per-user data folder named only in that folder's
`holdouts.json` (the redesign after 3.0's review round 2, a deviation from P4's sibling repo), so a lane is never
handed their path, and the guard is the second line; it still denies the old sibling `<project>-holdout`, for
a workbench split under a release candidate. After an amend's re-verify, `holdout.py reconcile` restores the
hidden entries and re-pins the split record's manifest hash, so Gate 4's "manifest changed after the split"
refusal fires only when reconcile refuses. A folder with `locks/` but no readable `rebuild_major`
marker counts as a workbench to the guard, so deleting the marker does not switch it off.

## Unchanged, with no eval in 2.x or 3.0

The autopilot usage threshold (a hook pauses a run at 80% of the 5-hour window) and the context limit (stop at
250k tokens) are unchanged from 2.2.0 and were never covered by an eval. They are listed here so the gap is on
the record rather than hidden by the table above.

## What was deleted

- **Agents** `miner`, `spec-writer`, `data-model-drafter`, `adr-drafter`, `rubric-judge` (D3), and their phase
  references (`g1-mining.md`, `g2-matrix.md`, `g3-slicing.md`, `g4a-architecture.md`, `g4b-contracts.md`,
  `architecture-default.md`, `rubrics/`).
- **Lane R** (D2): `rules_for.py`, `rule.schema.json`, `validate.py`'s rule checks, the `rules_recall.py` eval and
  its fixture (moved to `docs/rspec-pr/rules-recall/` for rspec), and CLAUDE.md's evals rule that measured
  recall there.
- **Scripts** `cite_excerpts.py`, `gate_facts.py`, `evidence_bundle.py` (the rubric judge's inputs), `erd.py`,
  `basis.py`, `lane_plan.py --specs` (and its `--amend`), and `playbook.py excerpt` with the ADR concern and
  citation checks.
- **Schemas** `feature`, `finding`, `rule`, `slice`.
- **Workbench folders** `findings/`, `matrix/`, `plan/specs/`, `contracts/`: a new workbench holds rspec's spec
  in `docs/` instead. `adr/` stays, for the vendored playbook and its scaffold manifest only (its README says so):
  the ADRs are rspec's, in `docs/decisions/`, and gate-3 locks both, so the stack a code repo is created from
  cannot change under a project when the plugin upgrades.
- **Evals and fixtures** for the deleted parts: `rules_for.py`, `rules_recall.py`, `cite_excerpts.py`,
  `gate_facts.py`, `evidence_bundle.py`, `playbook_excerpt.py`, and the `drafter-ab`, `instruction-shaped` and
  `rules-recall` fixtures.
