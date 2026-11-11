# Gate-4 eval check reads validate.py's FAIL and warn lines, not its ok line

## Why

**Request (verbatim):** "go ahead" (to the todo filed by 2026-11-11-s-contracts-1-2-0: fix eval/gates_rspec.py's "validate.py accepts the gate-4 lock" check and drop it and migration_3.py's item 18 from `.sdlc/baseline.md`).

**Bug:** `python3 skills/rebuild-pipeline/eval/gates_rspec.py` fails "validate.py accepts the gate-4 lock with its holdout and level2_waiver blocks" although `validate.py` exits 0 and prints "All artifacts valid." Root cause: the check (`gates_rspec.py:213-214`, added in b1bdc8a) asserts `"locks/gate-4.yaml" not in r.stdout + r.stderr`, but `validate.py` prints an `ok   <file>` line for every artifact it accepts (its output contract, `validate.py:25`, since 29e5dc7), so the accepted lock's own `ok   locks/gate-4.yaml` line fails it. `migration_3.py` item 18 runs `gates_rspec.py`, so it fails with it.

## Decisions

| Decision | Ruled out | Why |
|---|---|---|
| Fail only on a `FAIL locks/gate-4.yaml` or `warn locks/gate-4.yaml` line | Dropping the path check (exit code alone) | A warning about the lock is what the check exists to catch, and `validate.py` exits 0 on warnings |

## Acceptance criteria

- **AC-001** Given the eval's gate-4 workbench, when `gates_rspec.py` runs, then the "validate.py accepts the gate-4 lock" check passes, and the eval exits 0.
- **AC-002** Given that fix, `migration_3.py` passes, and both baseline rows added by 2026-11-11-s-contracts-1-2-0 are removed.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | skills/rebuild-pipeline/eval/gates_rspec.py › validate.py accepts the gate-4 lock with its holdout and level2_waiver blocks | `python3 skills/rebuild-pipeline/eval/gates_rspec.py` |
| AC-002 | skills/rebuild-pipeline/eval/migration_3.py › 18. G4b contracts and their `$ref` checks | `python3 skills/rebuild-pipeline/eval/migration_3.py` |

## Must never break

- The check still fails when `validate.py` reports the gate-4 lock as FAIL or warn.

## Out of scope

- The other three baseline rows (Windows-specific failures; they pass on macOS).

## Review

No review ran: no trigger fired (S, low risk, eval-only). AC-001 and AC-002 red then green; full suite passes with the two baseline rows removed.
