# 2026-11-16-m-reference-adapter-gates
Status: done
Process: 3
Change: docs/sdlc/changes/2026-11-16-m-reference-adapter-gates.md   (this feature's record for people)
Track: M   (sized up because: —; footprint: 8 files)
Risk: low
Top model: opus   (fable only if the user chose it)
Commands: test: `python3 -c "import glob,subprocess,sys; sys.exit(max([subprocess.call([sys.executable,f]) for f in sorted(glob.glob('skills/rebuild-pipeline/eval/*.py'))] or [0]))"`
Started: 2026-11-16
Base: 3c38309
Owner: tammai.it@gmail.com
Tool: claude-code
Current: Stage 4 – Ship

## Stages
- [x] 1 Define   — the change file, the plan sections below
- [x] 2 Build
- [x] 3 Review   — the change file's ## Review
- [ ] 4 Ship     — PR: (Learn: knowledge, recurring-defects.md)

## How the build runs
inline

## Handoff
- gate-4 lock checks: skills/rebuild-pipeline/scripts/gate.py _lock_gate4_checks; REQUIRED_PROTECTS at gate.py:69
- sources.yaml reference block read line-wise in validate.py:345 and gate.py posture()

## Tasks
1. **sources.yaml reference.adapter and its validation** — AC-001
   - Files: `skills/rebuild-pipeline/scripts/rebuild_init.py`, `skills/rebuild-pipeline/scripts/validate.py`
2. **adapter.py audit** — AC-002
   - Files: `skills/rebuild-pipeline/scripts/adapter.py`
3. **Gate 4 adapter checks and protects** — AC-003 AC-004
   - Files: `skills/rebuild-pipeline/scripts/gate.py`, `skills/rebuild-pipeline/eval/gates_rspec.py`
4. **Pipeline docs** — AC-005
   - Files: `skills/rebuild-pipeline/SKILL.md`, `skills/rebuild-pipeline/references/subagent-briefs.md`, `CHANGELOG.md`

## Public Surface
- command `adapter.py audit` — AC-002
- config `sources.yaml reference.adapter` — AC-001

## Gate log
- 2026-11-16 Stage 1: pass — plan not stopped for approval: low-risk M
- 2026-11-16 verify: only the test step fails, every failure in .sdlc/baseline.md
- 2026-11-16 Stage 2: pass — verify: only the baseline's 4 eval failures; drift recorded
- 2026-11-16 review: ran code (Public Surface: adapter.py audit, sources.yaml reference.adapter), not asked: low risk
- 2026-11-16 Stage 2: pass — round-1 fixes in; verify: only the baseline's 4 eval failures
- 2026-11-16 Stage 2: pass — round-3 fixes in (user chose one more fix round); verify: only the baseline's 4 eval failures
- 2026-11-16 Stage 2: pass — round-3 low bug R3-L1 fixed test first; verify: only the baseline's eval failures
- 2026-11-16 Stage 3: pass — review rounds 1-3 recorded; round 3 PASS; R3-L1 fixed
- 2026-11-16 Stage 4: baseline failures waived: only the test step failed; 3 listed in .sdlc/baseline.md

## Deviations
- 2026-11-16 skills/rebuild-pipeline/scripts/adapter.py audit, main What: the module's functions (the command is in Public Surface). Why: gate.py imports audit(); main is the CLI. Effect: none beyond the command.
- 2026-11-16 skills/rebuild-pipeline/scripts/gate.py reference_field, posture What: posture's sources.yaml field reader moved into reference_field. Why: Gate 4's adapter check reads reference.adapter the same way. Effect: posture() returns the same values.
- 2026-11-16 skills/rebuild-pipeline/scripts/gate.py _git_lines, adapter_files, _iso, _lock_gate4_level2_checks; schemas/lock.schema.json adapter_audit What: helpers for the adapter checks, the level-2 checks renamed under a wrapper, a lock key. Why: review round 1 (H2 tracked files only, H3 fail closed, M1 start vs last commit, M2 log git-ignored). Effect: Gate 4 with no adapter locks as before.
- 2026-11-16 skills/rebuild-pipeline/schemas/lock.schema.json What: an adapter_audit key. Why: Gate 4 records the adapter audit's result (review M1). Effect: optional; older locks still validate.
- 2026-11-16 skills/rebuild-pipeline/scripts/gate.py _git_paths, _unproven_http; skills/rebuild-pipeline/scripts/adapter.py parse_time, last_change What: helpers for round 2. Why: R2-H1 (every run since the adapter's last commit; level-2 HTTP criteria proven through this version), R2-M2 (aware times), R2-L1 (ls-files -z). Effect: none without reference.adapter: required.

## Open questions
-
