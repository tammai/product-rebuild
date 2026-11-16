# 2026-11-16-m-gh-9-g6-departure-fixes
Status: done
Process: 3
Change: docs/sdlc/changes/2026-11-16-m-gh-9-g6-departure-fixes.md   (this feature's record for people)
Track: M   (sized up because: —; footprint: 9 files)
Risk: low
Top model: opus   (fable only if the user chose it)
Commands: test: `python3 -c "import glob,subprocess,sys; sys.exit(max([subprocess.call([sys.executable,f]) for f in sorted(glob.glob('skills/rebuild-pipeline/eval/*.py'))] or [0]))"`
Started: 2026-11-16
Base: abc889e
Owner: tammai.it@gmail.com
Tool: claude-code
Verified: abc889e tree bb38a2977dccc426324b0785dc8cec8478db9fa4
Current: Stage 4 – Ship

## Stages
- [x] 1 Define   — the change file, the plan sections below
- [x] 2 Build
- [ ] 3 Review   — the change file's ## Review
- [ ] 4 Ship     — PR: (Learn: knowledge, recurring-defects.md)

## How the build runs
inline

## Handoff
- boundary.py _open_suite JUnit branch: skills/rebuild-pipeline/scripts/boundary.py:259
- bug-hunter departure rules: contracts/v1/contracts.py _rule_problem (uuid,int,iso8601,regex:)

## Tasks
1. **Departures explain JUnit failures at the boundary** — AC-001
   - Files: `skills/rebuild-pipeline/scripts/boundary.py`, `skills/rebuild-pipeline/eval/g6_eval.py`
2. **One departure rule vocabulary** — AC-002 AC-003
   - Files: `skills/rebuild-pipeline/scripts/departures.py`, `skills/rebuild-pipeline/scripts/validate.py`
3. **Lane copies support modules and cites criteria** — AC-004 AC-005 AC-006
   - Files: `skills/rebuild-pipeline/scripts/lane_plan.py`, `skills/rebuild-pipeline/eval/lanes_rspec.py`
4. **Two-digit feature IDs** — AC-007
   - Files: `skills/rebuild-pipeline/schemas/progress.schema.json`, `skills/rebuild-pipeline/eval/coverage_rspec.py`
5. **Release 3.2.1** — AC-008
   - Files: `.claude-plugin/plugin.json`, `CHANGELOG.md`

## Public Surface
- none

## Gate log
- 2026-11-16 Stage 1: pass — plan not stopped for approval: low-risk M
- 2026-11-16 verify: only the test step fails, every failure in .sdlc/baseline.md (lane_guards worktree, run_supervision x2, windows gate-guard CRLF)
- 2026-11-16 Stage 4: baseline failures waived: only the test step failed; 3 listed in .sdlc/baseline.md
- 2026-11-16 Stage 2: pass — no review: no trigger fired

## Deviations
- 2026-11-16 skills/rebuild-pipeline/scripts/departures.py rule_problem, rule_problems What: two new module functions. Why: append and validate.py must share one copy of bug-hunter's rule list. Effect: internal to the workbench scripts; no command or flag changes.
- 2026-11-16 skills/rebuild-pipeline/scripts/lane_plan.py support_files What: a new module function. Why: copy_to_lane must follow the specs' relative imports transitively. Effect: internal; lane open and refresh copy more files.

## Open questions
-
