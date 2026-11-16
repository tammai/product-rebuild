# G6 departures, lane copies and progress IDs (issue #9, 3.2.1)

## Why

> Fix GitHub issue #9 items 1, 2, 3, 5, 7 as product-rebuild 3.2.1: (1) boundary.py open-suite JUnit path must honour decided departures like the http path; (2) departures.py must not accept rule "any" (bug-hunter rejects it) — refuse it on append; (3) lane_plan.py copy_to_lane must copy support modules the open specs import; (5) lane_plan.py must run sdlc's `state.py cite <feature> <ids>`; (7) progress.schema.json feature key pattern must accept two or more digits. Items 4 and 6 are out of scope (4 goes to an sdlc issue draft).

Slice S2 of a real rebuild on 3.2.0 could not pass G6. A decided departure explained its Playwright failures, but the boundary still held the slice. The lanes' copied specs could not import their helpers, `/hunt --oracle` stopped on a departure rule the workbench had accepted, and `plan/progress.yaml` could not record rspec's two-digit feature IDs. Source: https://github.com/tammai/product-rebuild/issues/9

## Acceptance criteria

- **AC-001** (issue #9 §1) When an open Playwright (JUnit) test fails twice and a decided departure's match rule covers it, `boundary.py` prints `<criterion>: fails twice, explained by D-…`, writes no finding and does not hold the slice, the same as the HTTP path.
- **AC-002** (§2) `departures.append` refuses a match rule outside bug-hunter's departure vocabulary (`uuid`, `int`, `iso8601`, `regex:<valid pattern>`), plus the workbench's own `equiv-trace:<name>`, and writes nothing. `any` is no longer a rule, so it explains nothing.
- **AC-003** (§2) `validate.py` names a departure in `docs/departures.yaml` whose match rule is outside that vocabulary (an entry written by hand).
- **AC-004** (§3) Opening or refreshing a lane copies, with each open spec, the support modules it imports by relative path (`./x`, `../x`), and their own imports in turn.
- **AC-005** (§3) An import that leaves the acceptance bundle, or that resolves to no file in it, refuses the copy, and the lane keeps what it had.
- **AC-006** (§5) Opening a lane runs sdlc's `state.py cite <feature> <every cited criterion>` after `state.py new`.
- **AC-007** (§7) `validate.py` accepts rspec's two-digit feature IDs (`F-AB-01`) under `features:` and `feature_notes:` in `plan/progress.yaml`.
- **AC-008** Release: `.claude-plugin/plugin.json` 3.2.1 and a `CHANGELOG.md` entry.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | `skills/rebuild-pipeline/eval/g6_eval.py` › boundary › a Playwright test failing twice that a decided departure explains | `python3 skills/rebuild-pipeline/eval/g6_eval.py boundary` |
| AC-002 | `skills/rebuild-pipeline/eval/g6_eval.py` › departures › append refuses a match rule bug-hunter refuses | `python3 skills/rebuild-pipeline/eval/g6_eval.py departures` |
| AC-003 | `skills/rebuild-pipeline/eval/g6_eval.py` › departures › validate.py names a hand-written departure | `python3 skills/rebuild-pipeline/eval/g6_eval.py departures` |
| AC-004 | `skills/rebuild-pipeline/eval/lanes_rspec.py` › lane › support modules an open spec imports are copied | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py lane` |
| AC-005 | `skills/rebuild-pipeline/eval/lanes_rspec.py` › lane › an import that leaves the bundle is refused | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py lane` |
| AC-006 | `skills/rebuild-pipeline/eval/lanes_rspec.py` › lane › state.py cite records every cited criterion | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py lane` |
| AC-007 | `skills/rebuild-pipeline/eval/coverage_rspec.py` › reports › validate.py accepts two-digit feature IDs | `python3 skills/rebuild-pipeline/eval/coverage_rspec.py reports` |
| AC-008 | manual | version and changelog text, checked against the diff at Review |

## Must never break

- A hidden test never reaches a lane, whether through the manifest or through an import.
- An undecided (proposed) departure explains nothing. A JUnit failure no departure covers is still a `g6-open` finding.
- `equiv.py accept`'s `equiv-trace:<name>` departures keep explaining their traces.

## Decisions

| Decision | Chosen | Ruled out |
|---|---|---|
| Item 2: one vocabulary | Refuse `any` on append, name it in `validate.py`, and drop it from matching (`regex:.*` replaces it) | Keeping `any` in the workbench: `/hunt --oracle` stops on it |
| Item 3: which files to copy | Follow the relative imports of each copied JS/TS file, transitively, inside the bundle | Copying every non-test file in the bundle: it would bring `DECISIONS.md` and other criteria's files into the lane |
| Item 1: the observed value | Pointer none; the value is the failure line the boundary already prints | Parsing the JUnit failure message: `_junit_states` does not keep it, and `regex:` rules on the runner are enough to scope a departure |

## Out of scope

- Item 4 (sdlc `verify.py` and a recorded-spec Test cell a departure explains): drafted as an sdlc issue.
- Item 6 (recorded tests that speak the reference's API): needs a design decision at the pipeline level.
- bug-hunter also refuses `equiv-trace:<name>`, which `equiv.py accept` writes, so a workbench with an accepted trace also stops `/hunt --oracle`. That fix belongs in bug-hunter; drafted with the item 4 issue.

## Review

No review ran: low risk, no trigger fired; every AC red then green (verify.py). AC-008 checked by reading: plugin.json is 3.2.1 and CHANGELOG has a 3.2.1 entry naming each fix.
