# 2026-11-15-m-g5-cost-tiers
Status: done
Process: 3
Change: docs/sdlc/changes/2026-11-15-m-g5-cost-tiers.md   (this feature's record for people)
Track: M   (sized up because: —; footprint: 10 files)
Risk: low
Top model: opus   (fable only if the user chose it)
Commands: test: `python3 -c "import glob,subprocess,sys; sys.exit(max([subprocess.call([sys.executable,f]) for f in sorted(glob.glob('skills/rebuild-pipeline/eval/*.py'))] or [0]))"`
Started: 2026-11-15
Base: 457b960
Owner: tammai.it@gmail.com
Tool: claude-code
Current: Stage 4 – Ship

## Stages
- [x] 1 Define   — the change file, the plan sections below
- [x] 2 Build
- [x] 3 Review   — the change file's ## Review
- [ ] 4 Ship     — PR: (Learn: knowledge, recurring-defects.md)

## How the build runs
inline, this session

## Handoff
- boundary.py _budget() reads rebuild.yaml budgets block by regex (boundary.py:345); step 5 builds the hunt command at boundary.py:494
- holdout.observed() turns 'request failed: ... refused' into fail (holdout.py:529); boundary._http returns False for it, so a dead target writes findings
- holdout.py:534 withheld detail is a posture guard: keep

## Tasks
1. **Tier budgets in boundary and the scaffolded rebuild.yaml** — AC-001 AC-002
   - Files: `skills/rebuild-pipeline/scripts/boundary.py`, `skills/rebuild-pipeline/scripts/rebuild_init.py`, `skills/rebuild-pipeline/eval/gp_eval.py`
2. **Target health: preflight and stop on first refused** — AC-003 AC-004
   - Files: `skills/rebuild-pipeline/scripts/boundary.py`, `skills/rebuild-pipeline/scripts/holdout.py`, `skills/rebuild-pipeline/eval/g6_eval.py`
3. **Step 0 names criteria in --only** — AC-005
   - Files: `skills/rebuild-pipeline/scripts/lane_plan.py`, `skills/rebuild-pipeline/eval/lanes_rspec.py`
4. **Orchestrator guidance (fresh session per slice, boundary in a fresh agent, file-pointing briefs, verify scope mvp), release 3.2.0** — AC-001
   - Files: `skills/rebuild-pipeline/SKILL.md`, `skills/rebuild-pipeline/references/g5-build.md`, `skills/rebuild-pipeline/references/subagent-briefs.md`, `.claude-plugin/plugin.json`, `CHANGELOG.md`, `docs/MIGRATION-3.md`

## Public Surface
- config `budgets.hunters_per_slice_low` — AC-001
- config `budgets.bughunter_tokens_per_slice_low` — AC-001
- config `budgets.low_tier_slices` — AC-001

## Gate log
- 2026-11-15 Stage 1: pass — plan not stopped for approval: low-risk M
- 2026-11-15 verify: only the test step fails, all four failures listed in .sdlc/baseline.md (lane_guards worktree count, run_supervision x2, windows_and_upgrade CRLF); every AC passes
- 2026-11-15 review: ran code (Public Surface adds config keys), not asked: low risk
- 2026-11-15 Stage 2: pass — baseline-only test failures; code review fires on Public Surface
- 2026-11-15 verify after r1 fixes: only the four baseline failures; every AC and the new mid-run, block-list and zero-budget checks pass
- 2026-11-15 Stage 2: pass — r1 fixes in; closing check next
- 2026-11-15 r2 medium bugs fixed test first (R2-1..6, 9, 10); verify: only the four baseline failures, no drift
- 2026-11-15 Stage 2: pass — closing fixes in; review r2 PASS
- 2026-11-15 Stage 3: pass — review r2 PASS; Learn: recurring defect filed
- 2026-11-15 Stage 4: baseline failures waived: only the test step failed; 3 listed in .sdlc/baseline.md

## Deviations
- 2026-11-15 eval red step: What: the first verify.py red recorded a SyntaxError (literal newlines in two new eval strings), not the behaviour. Why: heredoc edit. Effect: tests repaired; red proven by hand by running the three groups against the old scripts (git stash): every AC's new check FAILs, AC-002's 3.1.0 no-regression half passes on both as intended
- 2026-11-15 docs/PLAYBOOK.md What: step 0 line now says --only <criterion IDs>. Why: it restated the rule step 0 changed. Effect: docs only
- 2026-11-15 holdout.py answers What: new module function, the one TCP connect boundary.py and holdout.py run share before any test. Why: AC-003/AC-004 preflight; one check on both paths. Effect: internal to the workbench scripts, not a public surface
- 2026-11-15 holdout.py unreachable What: new module function classifying a run-http 'request failed: ... refused' message. Why: AC-004; boundary's open suite and holdout.observed share it. Effect: internal, not a public surface
- 2026-11-15 skills/rebuild-pipeline/scripts/route.py What: a comment naming the two other copies of the budgets-block regex. Why: review R2-11, project CLAUDE.md asks to say when copies must change together. Effect: comment only
- 2026-11-15 holdout.py integrity What: run_one's missing/changed-since-gate-4 checks moved into a function cmd_run also calls before skipping a test while the build is down. Why: review R2-5, an outage must not hide a tampered hidden test. Effect: same checks, same messages; internal

## Open questions
-
