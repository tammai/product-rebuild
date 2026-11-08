# Shared contracts v1

## Why

**Request (verbatim):** implement docs/specs/rebuild-upgrade/01-shared-contracts.md

The spec is [docs/specs/rebuild-upgrade/01-shared-contracts.md](../../specs/rebuild-upgrade/01-shared-contracts.md) (copied from the rebuild-upgrade spec set, wave W1). It creates the canonical `contracts/v1/` (decision D1) that rspec, sdlc, bug-hunter and product-rebuild vendor byte-identical.

**The user's words:** via the Orca coordinator. Q1: run `/sdlc:setup` with recommended defaults. Q2: `contracts.py` parses a documented strict YAML subset itself; every YAML example in 01 must parse under it and ships as a valid fixture; anything outside the subset is a parse error with a line number. Q3: the spec was amended (01 line 19): header as a first-line comment in `.py`/`.md`/`.yaml`, first key `"$comment"` in `*.schema.json`, fixtures carry no header but are listed in `MANIFEST`. Proposals P4–P9 accepted (MANIFEST format, fixtures and tests inside `contracts/v1/`, `.gitattributes`, one part, no rc tag, no version bump, a `--profile` flag for C1 severity that follows 01's table, contracts version 1.0.0).

## Decisions

| Decision | Ruled out | Why |
|---|---|---|
| One stdlib file `contracts.py` holds the YAML subset parser, a small JSON Schema validator, every C1–C7 check, `run-http` and `vendor-check` | several modules; vendored PyYAML or jsonschema | the spec says stdlib only; one file is the simplest thing to vendor byte-identical |
| The schema validator refuses any keyword it does not implement | ignoring unknown keywords | design rule 6, no silent pass (same stance as `scripts/schemacheck.py`) |
| `MANIFEST`: line 1 `contracts-version: 1.0.0`, then `<sha256>  <relpath>` for every other file under `contracts/v1/`, sorted, LF; `__pycache__` excluded | hashing working-tree bytes after CRLF conversion | `.gitattributes` `contracts/v1/** -text` keeps the bytes identical on every OS (P4, P6) |
| `vendor-check <dir>` checks MANIFEST hashes, headers and runs every fixture; each consumer's drift test is that one call | a test per consumer written from scratch | one behaviour, one place; consumers stay a one-liner |
| Fixtures under `fixtures/<kind>/valid/` and `fixtures/<kind>/invalid/`; the runner infers the check from `<kind>` | an index file | an index file would need a header and its own format |
| C1 profile flag `--profile rspec|sdlc-s|sdlc-m|sdlc-l` (default `rspec`) selects the row of 01's table: example data is a warning in sdlc-s/m, an error in rspec and sdlc-l; source tags reverse-spec in rspec, forward-spec in sdlc | inferring the context from the file | the file alone cannot say which producer wrote it (P8) |
| Points 01 leaves open, settled in `CONTRACTS.md` and listed for the coordinator: `text_sha256` is over the criterion text after the `**ID**` through the end of the line (checkbox excluded); removed criterion form `- [ ] ~~**ID** text~~ removed: <reason>`; manual exemption `` `[manual: <reason>]` ``; acceptance manifest top level `{"contracts", "tests": [...]}`; account env value is a full header line (`Authorization: Bearer …` or `Cookie: …`); `MNB-<n>` lines name `test:` or `check:`; `regex:` added to the match rules because C5's example uses it | asking for each | each is a format detail inside the spec's latitude; listed in the report so a consumer can object before it adopts v1 |

**Proposals not asked for:** None.

## Acceptance criteria

- **AC-001** docs/specs/rebuild-upgrade/01-shared-contracts.md §C1: Given a story or change file, when `contracts.py criteria` runs, then it reports ID format and duplicates, grammar, example data (warning or error by profile, `[manual: …]` exempt), exactly one allowed source tag, and a removed criterion without a reason; `contracts.py id` checks single IDs.
- **AC-002** docs/specs/rebuild-upgrade/01-shared-contracts.md §C2: Given a reverse-spec story, when `contracts.py story` runs, then a missing section, an `Edge cases` section, a failure mode without `→ <criterion|MNB>` to an existing ID, an MNB line naming no test or check, and a difference without `→ D-<nnn>` are errors.
- **AC-003** docs/specs/rebuild-upgrade/01-shared-contracts.md §C3: Given `criteria.lock.json`, when `contracts.py lock` runs, then schema violations are errors and a `text_sha256` that no longer matches the criterion's text reports its effective level as 0.
- **AC-004** docs/specs/rebuild-upgrade/01-shared-contracts.md §C4: Given an `acceptance/` bundle, when `contracts.py bundle` runs, then a manifest entry with a bad field, a wrong `sha256`, a path outside its runner's folder, an invalid HTTP replay file, or any URL or secret in a test file fails it.
- **AC-005** docs/specs/rebuild-upgrade/01-shared-contracts.md §C4 HTTP replay: Given HTTP replay files and `ACCEPT_BASE_URL`, when `contracts.py run-http` runs, then it seeds, sends each step with the account header from `ACCEPT_ACCOUNT_<NAME>`, checks status, `equals`, `rule` (`uuid|int|iso8601|same-as:<capture>|regex:`) and `capture`, substitutes `{capture}` in paths, prints JUnit XML and exits non-zero on any failure or on a missing target.
- **AC-006** docs/specs/rebuild-upgrade/01-shared-contracts.md §C5: Given `departures.yaml`, when `contracts.py departures` runs, then an entry without `decided_by` (and not `status: proposed`) or with a bad field is an error, and a proposed entry makes it exit with "blocks" naming it.
- **AC-007** docs/specs/rebuild-upgrade/01-shared-contracts.md §C6: Given finding files, when `contracts.py finding` runs, then bad fields and a `route` that does not match its `class` are errors, and a finding without `verified_by.result: reproduced` is reported as not routed.
- **AC-008** docs/specs/rebuild-upgrade/01-shared-contracts.md §C7: Given `cost.jsonl`, when `contracts.py cost` runs, then a bad line is an error with its line number and valid lines are summed by stage, with unreported tokens counted separately.
- **AC-009** Coordinator Q2 (01 §C4, §C5 YAML): Given YAML in the documented subset, when it is parsed, then every YAML example in 01 parses to the expected data, and anchors, aliases, tags, block scalars, multiple documents, duplicate keys or bad indentation fail with the line number.
- **AC-010** docs/specs/rebuild-upgrade/01-shared-contracts.md §Decisions (Distribution), §Acceptance: Given `contracts/v1/`, when `contracts.py vendor-check` runs (this repo's drift test does), then it passes on the committed copy, every valid fixture passes and every invalid one fails, and a changed byte, a missing or extra file, or a missing `contracts-version` header fails it.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | contracts/v1/test_contracts.py › TestC1Criteria | `python3 contracts/v1/test_contracts.py TestC1Criteria` |
| AC-002 | contracts/v1/test_contracts.py › TestC2Story | `python3 contracts/v1/test_contracts.py TestC2Story` |
| AC-003 | contracts/v1/test_contracts.py › TestC3Lock | `python3 contracts/v1/test_contracts.py TestC3Lock` |
| AC-004 | contracts/v1/test_contracts.py › TestC4Bundle | `python3 contracts/v1/test_contracts.py TestC4Bundle` |
| AC-005 | contracts/v1/test_contracts.py › TestC4RunHttp | `python3 contracts/v1/test_contracts.py TestC4RunHttp` |
| AC-006 | contracts/v1/test_contracts.py › TestC5Departures | `python3 contracts/v1/test_contracts.py TestC5Departures` |
| AC-007 | contracts/v1/test_contracts.py › TestC6Finding | `python3 contracts/v1/test_contracts.py TestC6Finding` |
| AC-008 | contracts/v1/test_contracts.py › TestC7Cost | `python3 contracts/v1/test_contracts.py TestC7Cost` |
| AC-009 | contracts/v1/test_contracts.py › TestYamlSubset | `python3 contracts/v1/test_contracts.py TestYamlSubset` |
| AC-010 | skills/rebuild-pipeline/eval/contracts_v1.py › vendor-check on the committed copy and tampered copies | `python3 skills/rebuild-pipeline/eval/contracts_v1.py` |

## Must never break

- No file under `contracts/v1/` imports anything outside the Python standard library, and it runs on Python 3.9+.
- A check that cannot run says `not run: <reason>` and exits non-zero; it never passes (README design rule 6).
- No test file in a bundle carries a URL or a secret; targets come only from environment variables.
- Existing scripts, schemas and evals (`skills/rebuild-pipeline/schemas/finding.schema.json` included) are untouched.

## Failure modes

- Untrusted input: spec and finding files are written by agents; the parser and checks must fail with a message, never a traceback → AC-009, AC-001–AC-008 invalid fixtures.
- Line-ending conversion on Windows checkouts would change the hashed bytes → `.gitattributes` and AC-010.
- `run-http` against an unreachable target → reported as a failed test case with the error, exit non-zero → AC-005.

## Out of scope

- Vendoring into rspec, sdlc and bug-hunter, and their drift tests: their own parts (02–04). Each needs the same `.gitattributes` line.
- Applying `normalize` departure rules inside `run-http`, and the playwright, maestro and cli runners: C4 names only `run-http` as the runner `contracts.py` provides.
- Detecting a renumbered or reused criterion ID across two versions of a file: needs history; `criteria` checks duplicates and numbering within one file.
- Moving `hidden` tests out of a bundle (05, P4) and retiring the plugin's own `finding.schema.json` (05).
- A release tag or version bump: product-rebuild 3.0 is cut after W5.

## Review

- **Recommended and chosen:** code, default depth. It fired because the track is L and `## Public Surface` is not `- none`. Security did not fire: risk is low and no `areas.sensitive` path was touched. Chosen by the trigger list (L, self-chosen).
- **Verdicts:**
  - code-reviewer → `.sdlc/.work/findings/2026-11-08-l-shared-contracts-v1/code-reviewer-r1.md` → FAIL (CR-1 to CR-7).
  - code-reviewer → `code-reviewer-r2.md` → PASS: all eight fixed, no fix added a bug.
- **Fixed:** each with a failing test first, in `contracts/v1/test_contracts.py`.
  - CR-1: the YAML parser crashed on an empty key and on a flow value cut off at the end of the line. Both now raise a YamlError with the line (`TestYamlSubset`).
  - CR-2: a criterion with unclosed bold, and `expect.json` that is not a list, crashed. Both are now errors (`test_malformed_lines_are_errors_not_crashes`, `test_json_checks_must_be_a_list`).
  - CR-3: manifest and seed paths could climb out of the bundle and escape the URL and secret scan. They are now rejected (`test_paths_stay_inside_the_bundle`).
  - CR-4: non-UTF-8 bundle files were skipped by the scan. They are now scanned (`test_non_utf8_file_is_still_scanned`).
  - CR-5: `lock` without a root passed with a warning. It is now an error, and the CLI `--root` defaults to the current directory (`test_hash_not_checked_without_root`).
  - CR-6: a target with no scheme or not speaking HTTP crashed `run-http`. Each is now a failed test case (`test_bad_target_is_a_failed_case_not_a_crash`).
  - CR-7: `criteria` on a file with no criterion lines passed. It is now an error (`test_malformed_lines_are_errors_not_crashes`).
  - CR-8: the MANIFEST version error now shows the line it found. Low, no test.
  - New invalid fixtures for CR-1, CR-2 and CR-3 ship in `fixtures/`.
- **Tickets:** round 2's ticket T-1 was a Windows drive-relative seed path (`C:x.yaml`) slipping past the bundle-path check. It was a bug in this change's code, so it was fixed, not deferred: rejected on every OS, with its test in `test_paths_stay_inside_the_bundle`. No reviewer re-ran on it; its test was seen failing, then passing. No tickets remain.
- **Drift and manual checks:** three Deviations lines.
  - The module functions exported for the tests.
  - The fixture files and the exception classes.
  - The fixtures added in review.
  - No `manual` ACs. The project test command still exits 1, only on the evals listed in `.sdlc/baseline.md`. That list's `run_supervision.py` row was corrected during the build to name its second pre-existing failure, confirmed on 5820b38.
- **Lessons filed:** None.
