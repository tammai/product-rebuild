# Known failures baseline

<!-- Written by /sdlc:setup (sdlc v3.2.1). Yours from then on: the plugin never overwrites it.
     Review (Stage 3) fails only on failures NOT listed here. Rules:
     - Shrinks on its own: when a listed item passes, the build removes it and says so in the change file's `## Review`.
     - Never grows silently: adding an item needs the user's OK and a Deviations entry in that feature's state.md.
     - Fixing items is its own S-track work, not a side job inside a feature. -->

Recorded: 2026-11-08 at commit 5820b38, running each command in `.sdlc/config.json`

## Failing tests

| Package | Test (file › name) | Failure, one line | Since |
|---|---|---|---|
| (root) | eval/lane_guards.py › a lane worktree counts through its main repo | FAIL on this machine (Windows) | 5820b38 |
| (root) | eval/run_supervision.py › a dead driver is named with its phase; watch exits 2 on a dead driver | FAIL (both, confirmed on 5820b38) | 5820b38 |
| (root) | eval/windows_and_upgrade.py › gate-guard blocks an edit under a CRLF lock file | FAIL | 5820b38 |

## Lint and type errors

Counts per rule and file. Review fails if any count goes **up**, or a rule/file appears that isn't listed.

| Package | Tool | Rule | File | Count |
|---|---|---|---|---|
| — | none | | | |

## Build warnings / other

- none
