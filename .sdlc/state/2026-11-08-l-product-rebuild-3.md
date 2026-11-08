# 2026-11-08-l-product-rebuild-3
Status: active
Process: 3
Change: docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md   (this feature's record for people)
Track: L   (sized up because: —; footprint: 16 files)
Risk: low
Top model: opus   (fable only if the user chose it)
Commands: test: `python3 -c "import glob,subprocess,sys; sys.exit(max([subprocess.call([sys.executable,f]) for f in sorted(glob.glob('skills/rebuild-pipeline/eval/*.py'))] or [0]))"`
Started: 2026-11-08
Base: 3274d37
Owner: tammai.it@gmail.com
Tool: claude-code
Slice: B2   Slice base: 556ddef   Slice gates: none
Current: Stage 2 – Build

## Stages
- [x] 1 Define   — the change file, the plan sections below
- [ ] 2 Build
- [ ] 3 Review   — the change file's ## Review
- [ ] 4 Ship     — PR: (Learn: knowledge, recurring-defects.md)

## How the build runs
parts in fresh sessions: each backlog part is its own coordinator task

## Handoff
- workbench marker: hooks/scripts/hooklib.py REBUILD_MAJOR + is_current_workbench; rebuild_init.py PIPELINE_YAML; upgrade.py major fence; scaffold-repo/scripts/scaffold.py checks it too
- lanes are lane-worker subagents of a session started in the project's parent dir (g5-build.md Guardrails), so lane detection uses the payload agent_type
- reference checkout fallbacks: preflight.py checkout_candidates

## Tasks
1. **B1 Dependencies and version** — AC-001
   - Files: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md`
2. **B1 Posture field** — AC-002
   - Files: `skills/rebuild-pipeline/scripts/validate.py`, `skills/rebuild-pipeline/scripts/rebuild_init.py`, `skills/rebuild-pipeline/references/g0-reference.md`, `skills/rebuild-pipeline/eval/reference_guard.py`
3. **B1 P3 guard** — AC-003 AC-004
   - Files: `hooks/scripts/reference_guard.py`, `hooks/scripts/hooklib.py`, `hooks/hooks.json`, `README.md`, `skills/rebuild-pipeline/eval/reference_guard.py`
4. **B1 Refuse 2.x workbenches** — AC-005
   - Files: `hooks/scripts/hooklib.py`, `skills/rebuild-pipeline/scripts/rebuild_init.py`, `skills/rebuild-pipeline/scripts/upgrade.py`, `skills/rebuild-pipeline/SKILL.md`, `skills/scaffold-repo/scripts/scaffold.py`, `commands/rebuild.md`, `docs/PLAYBOOK.md`, `skills/rebuild-pipeline/eval/v0_fence.py`, `skills/rebuild-pipeline/eval/lane_guards.py`, `skills/rebuild-pipeline/eval/scaffold_repo.py`
5. **B2 P2 wiring** — AC-006
   - Files: `skills/rebuild-pipeline/SKILL.md`, `skills/rebuild-pipeline/scripts/gate.py`
6. **B3 Holdout and slice loop** — AC-007 AC-008
   - Files: `skills/rebuild-pipeline/scripts/holdout.py`, `hooks/scripts/flows_guard.py`, `skills/rebuild-pipeline/scripts/flows.py`
7. **B4 G6 and routing** — AC-009
   - Files: `skills/rebuild-pipeline/scripts/route.py`, `skills/rebuild-pipeline/scripts/boundary.py`, `skills/rebuild-pipeline/scripts/parity.py`, `skills/rebuild-pipeline/scripts/equiv.py`
8. **B5 GP, budgets, autopilot** — AC-010
   - Files: `skills/rebuild-pipeline/scripts/gate.py`, `skills/rebuild-pipeline/references/gp-production.md`
9. **B6 Capability table, deletions, docs** — AC-011
   - Files: `docs/MIGRATION-3.md`, `README.md`, `docs/PLAYBOOK.md`

## Public Surface
- config `sources.yaml reference.posture` — AC-002
- dependency `rspec >=0.11.0-rc.1 <1` — AC-001
- dependency `bug-hunter >=0.4.0-rc.1 <1` — AC-001

## Gate log
- 2026-11-08 Stage 1: pass — plan self-approved (L): (1) part-1 ACs 001-005 map to 05 Decisions/P3/P4/D7, later parts' ACs 006-011 to P1-P10, trace has no refs to check; (2) no open questions; (3) every decision answered by the coordinator (Q1-Q7, all as proposed); (4) no proposal beyond the request, nothing irreversible
- 2026-11-08 B2 ACs refined: AC-006 narrowed to gate order and rspec artifacts; AC-012 (Gate 4 level 2 floor), AC-013 (status reads rspec progress.py) and AC-014 (skill routing, manual) added from the coordinator's pr-2 answers

## Deviations
- 2026-11-08 surface What: script-internal functions allowed, bash_reaches, check, denied, denied_roots, guard, init_repo, is_lane, main, marked, posture_of, run, set_reference, tool_reaches, w (hooks/scripts/reference_guard.py and the evals) read as new exports. Why: they are functions inside a hook and eval scripts, imported by nothing. Effect: none; Public Surface unchanged.
- 2026-11-08 verify What: the project test command exits 1. Why: only baselined evals fail (windows_and_upgrade 1 failure, rules_recall usage); every AC test and the drift check pass; reference_guard.py and v0_fence.py all passed. Effect: B1 committed with plain git; Review and Ship run at Feature close.
- 2026-11-08 skills/rebuild-pipeline/eval/gate_status.py What: its G1-mining cases and adr/ proposal cases moved to the 3.x gate order and rspec's docs/decisions/. Why: 05 P2 removed G1 mining and moved ADRs to rspec; the eval tested the removed behaviour. Effect: same coverage on the 3.x paths; gate order and lock checks are in gates_rspec.py.
- 2026-11-08 surface What: script-internal functions contracts, criteria, gate, lock_text, rspec_config, rspec_json, rspec_progress_line, rspec_root, through_gate2, workbench (gate.py and the evals) read as new exports. Why: functions inside a vendored script and an eval, imported by nothing outside them. Effect: none; Public Surface lists the one new flag and env var.
- 2026-11-08 skills/rebuild-pipeline/scripts/upgrade.py What: B1's refusal message named the retired 0.x plugin, which eval/no_bigin.py forbids; the 0.x name was dropped from the message (SKILL.md, an allowed line, still names it). Why: a B1 regression the B1 verify run did not separate from the baselined failures. Effect: no_bigin.py passes again; the 2.x and 1.x messages still name 2.2.0 and 1.6.0.
- 2026-11-08 verify (B2) What: the project test command exits 1. Why: only the five evals in .sdlc/baseline.md fail (lane_guards, lane_plan, run_supervision, windows_and_upgrade, rules_recall usage); gates_rspec.py, gate_status.py, no_bigin.py, reference_guard.py and v0_fence.py pass, as does every AC and the drift check. Effect: B2 committed with plain git; Review and Ship run at Feature close.

## Open questions
-
