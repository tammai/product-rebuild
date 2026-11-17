# 2026-11-17-s-upgrade-dup-keys
Status: done
Process: 3
Track: S   (footprint: 3 files)
Risk: low
Top model: opus
Base: 8bce45d
Owner: tammai.it@gmail.com
Tool: claude-code
Verified: 8bce45d tree 8c333ef9679cc73264405a0e883c385e645c9390
Current: Stage 4 – Ship

## Tasks
1. **Backslash key wins over its twin** — AC-001
   - Files: `skills/rebuild-pipeline/scripts/upgrade.py`, `skills/rebuild-pipeline/eval/upgrade_manifest_keys.py`, `CHANGELOG.md`

## Public Surface
- none

## Gate log
- 2026-11-17 Stage 1: pass
- 2026-11-17 Stage 4: baseline failures waived (listed in .sdlc/baseline.md): lane_guards.py › a lane worktree counts through its main repo, run_supervision.py › a dead driver is named with its phase, run_supervision.py › watch exits 2 on a dead driver, with the evidence the plain check prints, windows_and_upgrade.py › gate-guard blocks an edit under a CRLF lock file
- 2026-11-17 Stage 2: pass — no review: no trigger fired

## Deviations
-

## Open questions
-
