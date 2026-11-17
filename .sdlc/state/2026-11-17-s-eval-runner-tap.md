# 2026-11-17-s-eval-runner-tap
Status: done
Process: 3
Track: S   (footprint: 4 files)
Risk: low
Top model: opus
Base: 7558bde
Owner: tammai.it@gmail.com
Tool: claude-code
Verified: 7558bde tree a655a93f94236bed015832ba3cc1e1da0f72e2f2
Current: Stage 4 – Ship

## Tasks
1. **Suite runner with TAP failure lines** — AC-001 AC-002
   - Files: `skills/rebuild-pipeline/eval/_run_all.py`, `skills/rebuild-pipeline/eval/run_all_eval.py`, `.sdlc/config.json`, `.sdlc/baseline.md`

## Public Surface
- none

## Gate log
- 2026-11-17 Stage 1: pass
- 2026-11-17 Stage 4: baseline failures waived (listed in .sdlc/baseline.md): lane_guards.py › a lane worktree counts through its main repo, run_supervision.py › a dead driver is named with its phase, run_supervision.py › watch exits 2 on a dead driver, with the evidence the plain check prints, windows_and_upgrade.py › gate-guard blocks an edit under a CRLF lock file
- 2026-11-17 Stage 2: pass — no review: no trigger fired

## Deviations
- 2026-11-17 skills/rebuild-pipeline/eval/_run_all.py main, skills/rebuild-pipeline/eval/run_all_eval.py check, w What: module-level functions of the new runner and its eval. Why: plain scripts, like every eval here; nothing imports them. Effect: none.

## Open questions
-
