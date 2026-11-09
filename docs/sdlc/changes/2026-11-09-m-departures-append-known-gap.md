# Departures append-only after Gate 1; client-only shape ships as a known gap

## Why

**Request (verbatim):** Two user decisions (2026-11-09) to apply before release, through sdlc as one small change, test-first:
1. Gate 1 and departures, option (a). 05-product-rebuild.md's Gate 1 row in C:/Users/Admin/orca/rebuild-upgrade is updated (re-copy it): Gate 1 locks features.md and domain.md; departures.yaml is not hashed but append-only from Gate 1 on. Every entry needs decided_by; a proposed entry blocks the gates that read it (C5); Gate 1 records the IDs present at its lock, and validate.py fails when one of those is removed or changed. departures.py gate1_allows_append is the single switch (it currently refuses appends after Gate 1): make it allow appends under those rules, and remove departures.yaml from gate-1's hashed set. Tests: an append after Gate 1 is accepted; removing or editing a recorded entry fails validation; a proposed entry still blocks.
2. docs/MIGRATION-3.md row 19 (client-only target shape: transcribe an existing API, on-device inventory): ship as a known gap in 3.0.0. Row text says so, with rspec's modernize track as the partial owner; migration_3.py must accept a known-gap row (no test cited) without failing, and README/CHANGELOG list it under known issues.
Also bump nothing (stays 3.0.0-rc.1).

Under 3.0.0-rc.1 a departure accepted at G6 (flows.py unlock --weakens, equiv.py accept) was refused once Gate 1
had locked, because Gate 1 hashed the whole registry. The user chose to keep Gate 1's protection for what it
approved and let later decisions land: the registry grows, but what Gate 1 saw cannot be removed or rewritten.
The client-only target shape has only rspec's modernize track behind it; the user chose to ship it as a known gap
rather than hold 3.0.0.

**The user's words:** the two decisions above, relayed by the coordinator. None asked.

## Decisions

| Decision | Ruled out | Why |
|---|---|---|
| Gate 1 records each departure's ID with a sha256 of the parsed entry (`departures_at_lock:` in `locks/gate-1.yaml`) | IDs only; a hash of the raw text | IDs alone cannot see an edit; raw text would fail on CRLF or a reflow that changes nothing |
| A recorded ID must appear exactly once with the same hash | first match wins | a later entry reusing `D-001` would otherwise widen what that departure explains |
| Gate 1 refuses to lock while any departure is `proposed` | recording proposed entries | deciding a recorded proposed entry would read as changing it; C5 already says a proposed entry blocks the gates that read it, and Gate 1 now reads the registry |
| A gate-1 lock written before this change (it hashes departures.yaml) still refuses appends, telling the user to reopen and lock again; a lock taken now drops departures.yaml from gate-1's `protects:` even when an rc.1 scaffold listed it | migrating old lock files | an append under an old lock would break its hash; re-locking is the logged way out |
| Row 19 cites no test and its Status is `known gap`; migration_3.py waives the proof only for that status, still requiring an owner | keeping rspec's modernize test as row 19's proof | with a proof the row would pass without the eval change, and the test covers only rspec's part |

**Proposals not asked for:** None.

## Acceptance criteria

- **AC-001** Given a workbench whose gate-1 `protects:` lists `docs/departures.yaml` (as an rc.1 scaffold did), when gate-1 locks, then it hashes features.md and domain.md and not departures.yaml; a new scaffold does not list departures.yaml.
- **AC-002** Given a proposed departure in the registry, when gate-1 is locked, then the lock is refused naming it.
- **AC-003** Given decided departures, when gate-1 locks, then the lock records each one's ID with a hash.
- **AC-004** Given gate-1 locked, when a decided departure is appended (flows.py unlock --weakens), then it is written after the existing entries and validate.py reports no departure problem.
- **AC-005** Given gate-1 locked, when a recorded departure is edited, then validate.py fails naming it as changed.
- **AC-006** Given gate-1 locked, when a recorded departure is removed, then validate.py fails naming it as removed.
- **AC-007** Given a capability-table row whose Status is `known gap`, an owner and no test cited, when migration_3.py runs, then it passes; row 19 is such a row naming rspec's modernize track as partial owner.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | skills/rebuild-pipeline/eval/gates_rspec.py › order (gate-1 hashes features.md and domain.md, not departures.yaml) | `python3 skills/rebuild-pipeline/eval/gates_rspec.py order` |
| AC-002 | skills/rebuild-pipeline/eval/g6_eval.py › departures (gate-1 refuses while a departure is proposed) | `python3 skills/rebuild-pipeline/eval/g6_eval.py departures` |
| AC-003 | skills/rebuild-pipeline/eval/g6_eval.py › departures (gate-1 records the departures present) | `python3 skills/rebuild-pipeline/eval/g6_eval.py departures` |
| AC-004 | skills/rebuild-pipeline/eval/g6_eval.py › departures (an append after gate-1 is accepted) | `python3 skills/rebuild-pipeline/eval/g6_eval.py departures` |
| AC-005 | skills/rebuild-pipeline/eval/g6_eval.py › departures (editing a recorded departure fails validation) | `python3 skills/rebuild-pipeline/eval/g6_eval.py departures` |
| AC-006 | skills/rebuild-pipeline/eval/g6_eval.py › departures (removing a recorded departure fails validation) | `python3 skills/rebuild-pipeline/eval/g6_eval.py departures` |
| AC-007 | skills/rebuild-pipeline/eval/migration_3.py › row 19 (known gap, no proof) | `python3 skills/rebuild-pipeline/eval/migration_3.py` |

## Must never break

- A proposed departure still blocks Gate 5 (`eval/gp_eval.py`, "refused a proposed departure").
- An unreadable departures registry never reads as empty: validate.py fails and gate-1 refuses to lock.
- A row with no proof and any other Status still fails migration_3.py.
- Reopening gate-1 clears its departure record with its hashes.
- The version stays 3.0.0-rc.1.

## Out of scope

- Checking every entry's `decided_by` in validate.py: `departures.append()` already requires it and readers ignore an undecided entry; the brief's tests do not ask for it.
- Building the client-only API transcription and device inventory.

## Review

**What fired and why.** No table row fired (low risk, Public Surface none, 5 source files). A code review ran anyway because the coordinator's brief set a review rule (sdlc's two-round cap). It was the built-in `code-review high --max-findings all`, a fresh forked context, and I rated its findings.

**Round 1: FAIL.** 15 findings. Reports are in `.sdlc/.work/findings/2026-11-09-m-departures-append-known-gap/code-reviewer-r1.md`.
- High CR-4: when nothing was recorded, an unreadable registry passed validate.py, which broke a must-never-break line. Fix: record_problems always loads the registry. Test: "an unreadable registry fails validation, before gate-1 records anything".
- Bugs fixed, each test-first:
  - CR-2: gate-5 now refuses on a broken record.
  - CR-3: record() refuses an entry with no decided_by.
  - CR-5: added tests for the rc.1 legacy-lock refusal and the broken-record refusal.
  - CR-6/CR-15: record() refuses an ID that is not D-<nnn>.
  - CR-7/CR-8: SKILL.md and pipeline.html updated.
  - CR-9: migration_3.py requires a known-gap row to be cited in README and CHANGELOG.
  - CR-10: gates_rspec checks that its injection happened.
- Non-bugs taken as cheap fixes:
  - CR-11: change-together comment at reopen.
  - CR-12: the gate-1 check moved into `_lock_gate1_checks`.
  - CR-13: a dropped protect is now printed.

**Round 2: PASS** (closing check, no high). Its medium and low bugs were fixed test-first and closed by verify:
- R2-1: decided() raises while a recorded departure is changed, so holdout.py, route.py and gate-5 fail closed. explained_by() warns and returns None.
- R2-2: load() refuses non-text field names, which would have caused a TypeError in digest.
- R2-3: a blank or non-text decided_by is undecided.
- R2-4/R2-5: docs now describe the old lock by its content and list every gate-1 refusal.
- R2-6: the known-gap citation must sit in the Known issues section.
- R2-8: the reason for a retired protect is stored beside its entry.

**Tickets (not fixed):**
- CR-1: departures appended after Gate 1 are not protected by the record. The spec row scopes the check to the IDs present at the lock; extending it is a spec decision.
- CR-14: append() reads the lock and the registry more than once.
- R2-7: recorded() parses the lock with a regex rather than yamlio. The D-<nnn> ID rule keeps the two in step.
- R2-9: `_lock_gate1_checks` takes an unused argv to share gate-4's dispatch loop.
- docs/img/pipeline.png is not re-rendered from the updated pipeline.html.

**Drift and changes since Define.** These are in the state file's Deviations. Gate-1 refuses more than AC-002 names: an entry with no decided_by, a blank decided_by, or an ID that is not D-<nnn>. Gate-5 also refuses on a broken record. The holdout_eval fixture now writes `[]` for the registry. The Out of scope line on decided_by is superseded: gate-1 now enforces it.

**Tests.** AC-001–007 were red first and pass now. The full suite fails only on the three `.sdlc/baseline.md` items: lane_guards worktree count, run_supervision dead driver ×2, windows_and_upgrade CRLF gate-guard.

**Lessons filed:** none. One recurring defect was added to `docs/sdlc/recurring-defects.md`.
