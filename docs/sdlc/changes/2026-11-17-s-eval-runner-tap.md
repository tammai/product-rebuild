# Eval suite names its failures for sdlc's baseline waiver

## Why

**Request (verbatim):** "Fix the runner first" — make the eval suite print `FAILED <name>` lines and an `N failed` summary so ship.py can read it, as its own small change, then ship the CRM lane/upgrade fixes.

sdlc 3.10's `ship.py --waive-baseline` matches failing tests to `.sdlc/baseline.md` only from runner output it knows (pytest, jest, vitest, node --test/TAP, go, unittest). This repo's evals print their own `FAIL  <check>` lines, so a change whose only failures are the baselined ones could not ship (2026-11-17-m-crm-lane-upgrade-fixes hit it).

## Decisions

| Decision | Ruled out | Why |
|---|---|---|
| A runner, `eval/_run_all.py`, ends the run with TAP `not ok N - <file> › <check>` lines and `# fail N` | pytest's `FAILED <name>` lines | ship.py reads a pytest name only up to its first space; every check name here has spaces. TAP takes the whole line, and ` › ` is a separator ship.py already strips to match the baseline's `file › name` cells |
| The baseline's run_supervision row is split into its two checks' exact names | leaving the combined cell | the waiver matches names exactly; one cell for two checks matches neither (not growth: the same two failures) |

## Acceptance criteria

- **AC-001** Given evals with failing checks, when the runner finishes, then it prints one `not ok N - <file> › <check>` line per failing check and `# fail N`.
- **AC-002** Given an eval that exits non-zero without a `FAIL` line, when the runner finishes, then it is named as a failure and the run exits non-zero; a file whose name starts with `_` is not run as an eval.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | skills/rebuild-pipeline/eval/run_all_eval.py › each failing check gets a TAP line | `python3 skills/rebuild-pipeline/eval/run_all_eval.py` |
| AC-002 | skills/rebuild-pipeline/eval/run_all_eval.py › an eval that exits non-zero with no FAIL line is still named | `python3 skills/rebuild-pipeline/eval/run_all_eval.py` |

## Must never break

- The suite still fails when any eval fails, and every eval's own output still reaches the reader.

## Out of scope

- The project `.claude/settings.json` allowlist still names the old test command; that is a permission setting for the user to change.

## Review

No review ran: no trigger fired.
