# 2026-11-09-m-departures-append-known-gap
Status: done
Process: 3
Change: docs/sdlc/changes/2026-11-09-m-departures-append-known-gap.md   (this feature's record for people)
Track: M   (sized up because: —; footprint: 13 files)
Risk: low
Top model: opus   (fable only if the user chose it)
Commands: test: `python3 -c "import glob,subprocess,sys; sys.exit(max([subprocess.call([sys.executable,f]) for f in sorted(glob.glob('skills/rebuild-pipeline/eval/*.py'))] or [0]))"`
Started: 2026-11-09
Base: ac9e95d
Owner: tammai.it@gmail.com
Tool: claude-code
Current: Stage 4 – Ship

## Stages
- [x] 1 Define   — the change file, the plan sections below
- [x] 2 Build
- [ ] 3 Review   — the change file's ## Review
- [ ] 4 Ship     — PR: (Learn: knowledge, recurring-defects.md)

## How the build runs
inline, this session

## Handoff
- gate-1 lock: skills/rebuild-pipeline/scripts/gate.py cmd_lock; reopen strips artifact_hashes..history, so the departure record sits between them
- lock.schema.json has additionalProperties false: departures_at_lock must be added
- other active features in .sdlc/state belong to earlier work and are left alone (coordinator asked for one new change)

## Tasks
1. **Departure record and append rule** — AC-002 AC-003 AC-004 AC-005 AC-006
   - Files: `skills/rebuild-pipeline/scripts/departures.py`, `skills/rebuild-pipeline/scripts/gate.py`, `skills/rebuild-pipeline/scripts/validate.py`, `skills/rebuild-pipeline/schemas/lock.schema.json`, `skills/rebuild-pipeline/eval/g6_eval.py`
2. **Gate-1 hashed set** — AC-001
   - Files: `skills/rebuild-pipeline/scripts/rebuild_init.py`, `skills/rebuild-pipeline/eval/gates_rspec.py`
3. **Known-gap rows** — AC-007
   - Files: `skills/rebuild-pipeline/eval/migration_3.py`, `docs/MIGRATION-3.md`
4. **Docs** — AC-001 AC-007
   - Files: `docs/specs/rebuild-upgrade/05-product-rebuild.md`, `docs/PLAYBOOK.md`, `README.md`, `CHANGELOG.md`, `docs/sdlc/changes/2026-11-09-m-departures-append-known-gap.md`

## Public Surface
- none

## Gate log
- 2026-11-09 Stage 1: pass — plan not stopped for approval: low-risk M
- 2026-11-09 verify: only the test step fails, every failure in .sdlc/baseline.md (lane_guards worktree count, run_supervision dead driver x2, windows_and_upgrade CRLF gate-guard); ACs 001-007 pass
- 2026-11-09 review: ran code-review high (no table row fired: 5 source files, surface none, low risk); run because the coordinator's brief set a review rule (2-round cap)
- 2026-11-09 Stage 2: pass — baseline-only test failures; review per coordinator brief
- 2026-11-09 Stage 3: fail — round 1: fix CR-2..10, 15; tickets CR-1, 14
- 2026-11-09 verify after round-1 fixes: test step fails only on .sdlc/baseline.md items (lane_guards worktree, run_supervision x2, windows_and_upgrade CRLF)
- 2026-11-09 Stage 2: pass — round-1 fixes in; baseline-only failures
- 2026-11-09 Stage 2: pass — review round 2 PASS; round-2 bugs fixed and verified; baseline-only test failures
- 2026-11-09 Stage 4: baseline failures waived: only the test step failed; 3 listed in .sdlc/baseline.md

## Deviations
- 2026-11-09 skills/rebuild-pipeline/scripts/departures.py What: new helpers digest, record, recorded, record_problems. Why: gate.py writes and validate.py and gate1_allows_append check the gate-1 record through one implementation. Effect: module-internal library functions, no CLI change.
- 2026-11-09 skills/rebuild-pipeline/eval/holdout_eval.py What: its fixture writes [] to docs/departures.yaml instead of {}. Why: gate-1 now reads the registry and rightly refuses one that is not a list. Effect: test fixture only.
- 2026-11-09 docs/img/pipeline.html and skills/rebuild-pipeline/SKILL.md What: Gate 1 lines updated to the append-only registry. Why: review round 1 (CR-7, CR-8) found them stale. Effect: docs only; pipeline.png is not re-rendered (ticket).
- 2026-11-09 skills/rebuild-pipeline/scripts/gate.py What: _lock_gate1_checks now returns (rc, extra) and gate-5 adds departures.record_problems; a dropped retired protect is printed. Why: review round 1 (CR-2, CR-12, CR-13). Effect: gate-5 refuses a tampered registry.
- 2026-11-09 skills/rebuild-pipeline/scripts/departures.py What: decided() raises while record_problems is non-empty; load() refuses non-text field names; _is_decided requires a non-blank text decided_by. Why: review round 2 (R2-1..R2-3). Effect: holdout.py and route.py explain nothing (with a warning) while a recorded departure is changed.

## Open questions
-
