# 2026-11-09-m-smoke-blockers-rc2
Status: done
Process: 3
Change: docs/sdlc/changes/2026-11-09-m-smoke-blockers-rc2.md   (this feature's record for people)
Track: M   (sized up because: —; footprint: 16 files)
Risk: high   (secrets: an account token committed in equivalence traces (S-38))
Top model: opus   (fable only if the user chose it)
Commands: test: `python3 -c "import glob,subprocess,sys; sys.exit(max([subprocess.call([sys.executable,f]) for f in sorted(glob.glob('skills/rebuild-pipeline/eval/*.py'))] or [0]))"`
Started: 2026-11-09
Base: 53b1b4c
Owner: tammai.it@gmail.com
Tool: claude-code
Verified: 53b1b4c tree 08a585f1517b9995c21a8277c0ce340c142a82c7
Current: Stage 4 – Ship

## Stages
- [x] 1 Define   — the change file, the plan sections below
- [x] 2 Build
- [ ] 3 Review   — the change file's ## Review
- [ ] 4 Ship     — PR: (Learn: knowledge, recurring-defects.md)

## How the build runs
inline, one part: seven small separate fixes; the brief says no subagents

## Handoff
- equiv record writes the request verbatim: skills/rebuild-pipeline/scripts/equiv.py record loop, doc['request']; do_request sends req.headers
- archive collision: lane_plan.py _archive dst = dest_dir/basename(src); change and state are both <feature>.md in sdlc 3.x
- existing g6_eval route check 'a second run is round 2' encodes S-55; rework it with a commit in proj/app between runs
- reference address: sources.yaml reference.run.base_url (rebuild_init writes it empty)

## Tasks
1. **S-38 equiv credentials** — AC-001 AC-002
   - Files: `skills/rebuild-pipeline/scripts/equiv.py`, `skills/rebuild-pipeline/eval/g6_eval.py`, `skills/rebuild-pipeline/references/g6-parity.md`
2. **S-54 G6 refuses the reference URL** — AC-003
   - Files: `skills/rebuild-pipeline/scripts/holdout.py`, `skills/rebuild-pipeline/scripts/boundary.py`, `skills/rebuild-pipeline/eval/g6_eval.py`
3. **S-55 no duplicate fix round** — AC-004
   - Files: `skills/rebuild-pipeline/scripts/route.py`, `skills/rebuild-pipeline/eval/g6_eval.py`
4. **S-57 archive keeps both files** — AC-005
   - Files: `skills/rebuild-pipeline/scripts/lane_plan.py`, `skills/rebuild-pipeline/eval/lanes_rspec.py`
5. **S-16 autopilot --help and unknown flags** — AC-006
   - Files: `skills/rebuild-pipeline/scripts/autopilot.py`, `skills/rebuild-pipeline/eval/gp_eval.py`
6. **S-37 validate detects a dropped hidden entry** — AC-007 AC-008
   - Files: `skills/rebuild-pipeline/scripts/validate.py`, `skills/rebuild-pipeline/eval/holdout_eval.py`
7. **S-42 known issue and version rc.2** — AC-009 AC-010
   - Files: `README.md`, `CHANGELOG.md`, `agents/lane-worker.md`, `.claude-plugin/plugin.json`, `skills/rebuild-pipeline/SKILL.md`

## Public Surface
- config `equiv request/trace field account: <NAME>` — AC-001
- env `ACCEPT_ACCOUNT_<NAME> read by equiv.py` — AC-001
- command `autopilot.py --help` — AC-006

## Gate log
- 2026-11-09 Stage 1: pass — approved by the coordinator (msg_77cf5e2b11ac), with S-54 tightening: open suite prints its target URL
- 2026-11-09 verify: only the test step fails, every failure in .sdlc/baseline.md (lane_guards a lane worktree counts through its main repo; run_supervision dead driver x2; windows_and_upgrade CRLF lock); AC-001..008 groups green when run alone; AC-009/010 manual
- 2026-11-09 review: ran security (Risk high) and code (Risk high; Public Surface not none; 7 source files), chosen: the coordinator approved the plan naming both (msg_77cf5e2b11ac)
- 2026-11-09 Stage 2: pass — verify: only baseline test failures
- 2026-11-09 Stage 3: fail — review r1: code-reviewer FAIL (CR-2,3,4,8,9 high + bugs), security FAIL (SEC-1,2,3,4 high + 6,8,9); fixing test-first
- 2026-11-09 round 1 fixes: every eval file passes but the 4 baseline failures (lane_guards worktree; run_supervision x2; windows_and_upgrade CRLF lock)
- 2026-11-09 Stage 2: pass — round 1 fixes in; suite = baseline only
- 2026-11-09 past round 2: user (Tam Mai, via coordinator msg_efdb9c008ece) chose one more fix round: A security SEC-10/R2-2, B fail-closed reference address + boundary stops on equiv refusal, C route attempts recorded only (archive of round-N fix lane, or route.py Sn --attempted); then one round-3 check, no round 4
- 2026-11-09 Stage 3: fail — review r2 FAIL; user chose one more round (A+B+C)
- 2026-11-09 round 3 fixes: full test command fails only on the 4 baseline tests
- 2026-11-09 Stage 2: pass — round 3 fixes in (A+B+C); suite = baseline only
- 2026-11-09 past round 3: user (Tam Mai, via coordinator msg_5599a8f3b6fc) chose one more fix round for R3-1 only, no 4th review; R3-2..R3-11 and security-r3 lows filed as tickets in docs/sdlc/todo.md; AC-004 and the S-55 Decisions row updated to the recorded-attempt design
- 2026-11-09 Stage 3: fail — review r3: code-reviewer FAIL R3-1; user chose one fix round for R3-1, no 4th review
- 2026-11-09 Stage 4: baseline failures waived: only the test step failed; 3 listed in .sdlc/baseline.md
- 2026-11-09 Stage 2: pass — local commit only, no push (coordinator brief)

## Deviations
- 2026-11-09 skills/rebuild-pipeline/scripts/holdout.py What: new function reference_target() (and helper _origin). Why: one check shared by boundary.py and holdout.py run (Decisions row S-54). Effect: none outside G6; not a public export beyond the vendored scripts.
- 2026-11-09 skills/rebuild-pipeline/scripts/route.py What: new function branch_tips(). Why: the commit signal for S-55's duplicate-round check (Decisions). Effect: route.py runs git for-each-ref in each repos.yaml repo.
- 2026-11-09 skills/rebuild-pipeline/scripts/route.py What: branch_tips() became fix_evidence() (commit set per code repo plus the criteria lock and departures hashes). Why: review r1 CR-3/CR-4/CR-5. Effect: opening a fix lane's branch is no fix; an amend or departure is; no readable code repo fails open with a message.
- 2026-11-09 skills/rebuild-pipeline/scripts/holdout.py What: _origin became _server() plus same_server(), and reference_target(url, var) reads sources.yaml with yamlio, failing closed. Why: review r1 CR-2/CR-8/SEC-4. Effect: equiv.py replay also calls it, and refuses a rebuild URL equal to the legacy URL.
- 2026-11-09 skills/rebuild-pipeline/scripts/route.py What: fix_evidence() replaced by attempted() and a new --attempted flag (user's round-3 decision C). Why: inferred fix evidence failed review twice (CR-3/4/5, R2-6). Effect: a round counts as attempted only when an archived fix lane or --attempted records it; SKILL.md documents the flag.
- 2026-11-09 docs/sdlc/changes/2026-11-09-m-smoke-blockers-rc2.md and docs/sdlc/todo.md What: AC-004, its test row and the S-54/S-55 Decisions rows rewritten after Review began; 17 review tickets filed in todo.md. Why: the user's round-2 and round-3 decisions replaced the S-55 design and asked for both (coordinator msg_5599a8f3b6fc). Effect: the record matches the built design; no AC added or dropped.
- 2026-11-09 waived round 3: R3-1 — fixed test-first (g6_eval equiv: an unconfigured lane is not run and G6 goes on; a refusal or unreadable account stops it) with no 4th review, by the user's decision (coordinator msg_5599a8f3b6fc); R3-2..R3-11 are tickets in docs/sdlc/todo.md
- 2026-11-09 Ship What: commit locally only, no push and no PR. Why: the coordinator's brief (commit locally, no push). Effect: no CI run; the branch stays local.

## Open questions
-
