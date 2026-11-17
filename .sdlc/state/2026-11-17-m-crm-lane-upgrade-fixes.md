# 2026-11-17-m-crm-lane-upgrade-fixes
Status: done
Process: 3
Change: docs/sdlc/changes/2026-11-17-m-crm-lane-upgrade-fixes.md   (this feature's record for people)
Track: M   (sized up because: —; footprint: 6 files)
Risk: low
Top model: opus   (fable only if the user chose it)
Commands: test: `python3 -c "import glob,subprocess,sys; sys.exit(max([subprocess.call([sys.executable,f]) for f in sorted(glob.glob('skills/rebuild-pipeline/eval/*.py'))] or [0]))"`
Started: 2026-11-17
Base: 7558bde
Owner: tammai.it@gmail.com
Tool: claude-code
Current: Stage 4 – Ship

## Stages
- [x] 1 Define   — the change file, the plan sections below
- [x] 2 Build
- [x] 3 Review   — the change file's ## Review
- [ ] 4 Ship     — PR: (Learn: knowledge, recurring-defects.md)

## How the build runs
inline: this session builds it, one part

## Handoff
- upgrade.py rel is native (_join=normpath); manifest keys from rebuild_init.py are '/': skills/rebuild-pipeline/scripts/upgrade.py:293-318, 550-556, 648-658
- lane_plan.py in-slice check: skills/rebuild-pipeline/scripts/lane_plan.py:637-640; rmtree: lane_plan.py:509-510

## Tasks
1. **Manifest keys with '/'** — AC-001
   - Files: `skills/rebuild-pipeline/scripts/upgrade.py`, `skills/rebuild-pipeline/eval/upgrade_manifest_keys.py`
2. **Fix lane accepts earlier slices' features** — AC-002 AC-003
   - Files: `skills/rebuild-pipeline/scripts/lane_plan.py`, `skills/rebuild-pipeline/eval/g6_eval.py`
3. **Lane bundle copy without wipe** — AC-004 AC-005
   - Files: `skills/rebuild-pipeline/scripts/lane_plan.py`, `skills/rebuild-pipeline/eval/lanes_rspec.py`
4. **Changelog** — AC-001
   - Files: `CHANGELOG.md`

## Public Surface
- none

## Test lock
- `skills/rebuild-pipeline/eval/g6_eval.py` sha256:634147ad179dc059ae4841af90d534ae62863db20664700ace2209f7b930bdbe
- `skills/rebuild-pipeline/eval/lanes_rspec.py` sha256:29e97419b5f89abf61cafb7287a4b754e1bd187107b0e31f1eda5e28c1b78827
- `skills/rebuild-pipeline/eval/upgrade_manifest_keys.py` sha256:8caf329c2df25172882ddca3d1ccef29e641dd419bffe802e545496a98ac921c
- `skills/rebuild-pipeline/eval/v0_fence.py` sha256:9f933d9e715f348846e68aef6f1f236a1959dd11f2731e50e185c54637bb7157

## Gate log
- 2026-11-17 Stage 1: pass — plan not stopped for approval: low-risk M
- 2026-11-17 verify: test step fails only on the 3 baseline items (lane_guards worktree count, run_supervision dead driver x2, windows_and_upgrade CRLF gate-guard); all 5 ACs pass
- 2026-11-17 verify: only the 4 baseline FAIL lines (lane_guards, run_supervision x2, windows_and_upgrade CRLF); AC-001..006 green
- 2026-11-17 review: ran code-review (no table row fired; voluntary: the diff narrows two safety barriers, the force-push backstop and the lane folder wipe that kept hidden tests out)
- 2026-11-17 Stage 2: pass — baseline-only test failures; voluntary code review
- 2026-11-17 Stage 3: fail — review r1: F1 F2 F3 F7 bugs to fix; F4 F8 F9 F10 fixed in passing; F5 F6 tickets
- 2026-11-17 Stage 2: pass — r1 fixes in; suite fails only on the 4 baseline lines
- 2026-11-17 Stage 3: fail — review r2 FAIL; user chose one more fix round: 4f wipe+copy all open tests up to the slice, 4i scrub substitutions
- 2026-11-17 verify r3: only the 4 baseline FAIL lines; AC-001..006 green
- 2026-11-17 Stage 2: pass — round 3 fixes in
- 2026-11-17 Stage 3: fail — review r3 FAIL (R3-1 high); user chose one more fix round: backstop relaxed only on simple lines; lane_plan Drop filter, lock hidden list, comments
- 2026-11-17 verify r4: only the 4 baseline FAIL lines; AC-001..006 green. Tickets: R3-2 heredoc lexing in guard_io, R3-9 earlier-slice integrity refusal, R3-12 lane lock blanking by manifest visibility
- 2026-11-17 Stage 2: pass — round 4 fixes in
- 2026-11-17 Stage 3: fail — review r4 FAIL (R4-1 $[ bypass); user chose fix $[ and ship
- 2026-11-17 Stage 2: pass — R4-1 fixed; baseline-only failures
- 2026-11-17 Stage 3: fail — review r5 FAIL (R5-1 quoted ${); user chose fix and ship
- 2026-11-17 Stage 2: pass — R5-1 fixed; baseline-only failures
- 2026-11-17 Stage 3: fail — review r6 FAIL (R6-1, R6-2); user chose allow-list then ship, falling back to dropping 4i if the closing check is not clean
- 2026-11-17 Stage 2: pass — allow-list in; baseline-only failures
- 2026-11-17 Stage 3: fail — review r7 FAIL (xargs carriers); user chose: drop 4i, revert bash_guard.py and v0_fence.py to Base, ship 4a/4b/4f
- 2026-11-17 Stage 2: pass — 4i dropped; suite fails only on the 4 baseline lines
- 2026-11-17 Stage 3: pass — review recorded; r7 waived (4i dropped)
- 2026-11-17 red re-recorded for AC-001..005 with lane_plan.py and upgrade.py temporarily at Base 7558bde (the S runner feature's ship had replaced the git-ignored verify record); both restored byte-identical from a copy
- 2026-11-17 Stage 4: baseline failures waived (listed in .sdlc/baseline.md): lane_guards.py › a lane worktree counts through its main repo, run_supervision.py › a dead driver is named with its phase, run_supervision.py › watch exits 2 on a dead driver, with the evidence the plain check prints, windows_and_upgrade.py › gate-guard blocks an edit under a CRLF lock file

## Deviations
- 2026-11-17 skills/rebuild-pipeline/eval/upgrade_manifest_keys.py check, listed, section, upgrade What: top-level helpers of the new eval script. Why: an eval is a plain script (constitution I), its helpers are module-level like every other eval's. Effect: none; nothing imports them.
- 2026-11-17 hooks/scripts/bash_guard.py, skills/rebuild-pipeline/eval/v0_fence.py What: AC-006 (4i) added: the legacy backstop matched a later segment's rm -f as git push -f. Why: user chose to add it to this PR once the CRM session sent the exact command. Effect: one more file, one more AC.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/lanes_rspec.py What: checks added for review r1 F1 (stale own test dropped), F2 (earlier slice's manifest entry kept), F7 (seed replaced whole). Why: round 1 found the copy fix left those gaps. Effect: stronger AC-004/AC-005 test.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/v0_fence.py What: check added for review r1 F3 (backstop reads -f after a redirection). Why: splitting on & and | cut 2>&1, &> and >|. Effect: stronger AC-006 test.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/lanes_rspec.py What: round 3 redesign of 4f: checks now prove the lane folder holds other features' open tests up to the slice, drops hidden/stale/seed files, and refuses an open test shared with a hidden one. Why: review r2 found selective clean-up leaked hidden tests; user chose one more fix round. Effect: AC-004/AC-005 reworded in the change file.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/v0_fence.py What: backstop cases for <&3, 0<&-, $(...), backticks, >(...), escaped quote and a push inside $(...). Why: review r2 R2-1/R2-2. Effect: stronger AC-006 test.
- 2026-11-17 skills/rebuild-pipeline/scripts/lane_plan.py copy_to_lane What: signature gains slice_id. Why: the folder is rebuilt from every feature up to the slice (4f redesign). Effect: both callers in lane_plan.py pass it; nothing outside the file calls it.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/v0_fence.py What: heredoc and escaped-separator force pushes still blocked; quoted heredoc mention not blocked; the $(...) case written as the old regex saw it. Why: review r3 R3-1/R3-3. Effect: stronger AC-006 test.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/lanes_rspec.py What: a Drop criterion's test is not carried; the shared-file refusal asserts its own message. Why: review r3 R3-8/R3-13. Effect: stronger AC-004/AC-005 test.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/v0_fence.py What: $[1|0] and $[0&1] force pushes added; quoted-heredoc check renamed to what it proves. Why: review r4 R4-1/R4-4. Effect: stronger AC-006 test.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/v0_fence.py What: quoted ${...} force pushes added; the CRM-shaped plain push now carries a quoted commit message with parentheses. Why: review r5 R5-1, and the raw-line check must not undo the CRM fix. Effect: stronger AC-006 test.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/v0_fence.py What: function/$@ and quote-misalignment force pushes added; single-quoted and $NAME plain lines must pass. Why: review r6 R6-1/R6-2/R6-4 (R6-5's CR case was not blocked by HEAD's backstop either, so it is not a backstop property). Effect: stronger AC-006 test.
- 2026-11-17 hooks/scripts/bash_guard.py, skills/rebuild-pipeline/eval/v0_fence.py What: 4i dropped; both files back to Base 7558bde, AC-006 removed from the change file. Why: review rounds 2-7 each found force pushes the split backstop let through that the original blocked; user chose to drop 4i and ship the rest. Effect: 4i moves to #16 for a tokenizer-level fix; CHANGELOG lists it as a known issue.
- 2026-11-17 waived round 7: R7-1 R7-2 R7-3 — all in hooks/scripts/bash_guard.py, reverted to Base when the user chose 'Drop 4i, ship the rest'; nothing they cite is in the diff any more
- 2026-11-17 skills/rebuild-pipeline/eval/_run_all.py, skills/rebuild-pipeline/eval/run_all_eval.py main What: this branch is stacked on 2026-11-17-s-eval-runner-tap (PR #17), so its files show in the diff against Base. Why: the user chose to fix the eval runner first so ship.py's baseline waiver can read the suite. Effect: merge PR #17 first; this PR's own diff is the CRM fixes.
- 2026-11-17 test-change skills/rebuild-pipeline/eval/lanes_rspec.py What: no content change; the file went through git stash and back while the runner fix shipped, which rewrote its line endings. Why: the user chose to fix the eval runner first. Effect: re-run red at Base for every AC, since the S feature's ship replaced the verify record.

## Open questions
-
