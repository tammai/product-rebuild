# 2026-11-08-l-shared-contracts-v1
Status: active
Process: 3
Change: docs/sdlc/changes/2026-11-08-l-shared-contracts-v1.md   (this feature's record for people)
Track: L   (sized up because: written spec with seven contracts (C1-C7) plus distribution; footprint: 40 files)
Risk: low
Top model: opus   (fable only if the user chose it)
Commands: test: `python3 -c "import glob,subprocess,sys; sys.exit(max([subprocess.call([sys.executable,f]) for f in sorted(glob.glob('skills/rebuild-pipeline/eval/*.py'))] or [0]))"`
Started: 2026-11-08
Base: 8dce668
Owner: tammai.it@gmail.com
Tool: claude-code
Verified: d00ba7a tree e2bc0c3aa6374fa3df256b37961f695f0fe8f18e
Current: Stage 4 – Ship

## Stages
- [x] 1 Define   — the change file, the plan sections below
- [x] 2 Build
- [x] 3 Review   — the change file's ## Review
- [ ] 4 Ship     — PR: (Learn: knowledge, recurring-defects.md)

## How the build runs
inline, one part

## Handoff
- spec: docs/specs/rebuild-upgrade/01-shared-contracts.md (line 19 amended by the user for headers)
- stdlib only, Python >= 3.9: test with py -3.10 (no 3.9 installed)
- Coordinator: no push, no merge to main, no tag; stop at branch and report via orca worker_done

## Tasks
1. **Contracts doc, schemas, .gitattributes** — AC-001 AC-002 AC-003 AC-004 AC-006 AC-007 AC-008 AC-009
   - Files: `contracts/v1/CONTRACTS.md`, `contracts/v1/criteria-lock.schema.json`, `contracts/v1/acceptance-manifest.schema.json`, `contracts/v1/departures.schema.json`, `contracts/v1/finding.schema.json`, `contracts/v1/cost-line.schema.json`, `.gitattributes`
2. **contracts.py validators, YAML subset, run-http, vendor-check** — AC-001 AC-002 AC-003 AC-004 AC-005 AC-006 AC-007 AC-008 AC-009 AC-010
   - Files: `contracts/v1/contracts.py`
3. **Unit tests and fixtures** — AC-001 AC-002 AC-003 AC-004 AC-005 AC-006 AC-007 AC-008 AC-009
   - Files: `contracts/v1/test_contracts.py`, `contracts/v1/fixtures/`
4. **MANIFEST and drift eval** — AC-010
   - Files: `contracts/v1/MANIFEST`, `skills/rebuild-pipeline/eval/contracts_v1.py`
5. **Spec copy and docs** — AC-010
   - Files: `docs/specs/rebuild-upgrade/01-shared-contracts.md`, `CHANGELOG.md`

## Public Surface
- command `contracts.py` — AC-001
- config `contracts/v1/MANIFEST` — AC-010
- env `ACCEPT_BASE_URL` — AC-005
- env `ACCEPT_ACCOUNT_<NAME>` — AC-005

## Gate log
- 2026-11-08 Stage 1: pass — plan self-approved (L): every AC cites 01 and trace passes; open questions empty; decisions settled by spec + coordinator answers Q1-Q3/P4-P9, format details listed for the coordinator; no proposals, nothing irreversible
- 2026-11-08 verify: only the test step fails, and every failing eval is in .sdlc/baseline.md (lane_guards, lane_plan, rules_recall without args, run_supervision x2, windows_and_upgrade); contracts_v1.py and all AC tests pass. Baseline row for run_supervision corrected to name its second pre-existing failure (checked on 5820b38).
- 2026-11-08 Stage 2: pass — verify: all ACs green; test step fails only on baseline-listed evals (logged)
- 2026-11-08 review: ran code-reviewer default (Code default: L, Public Surface not none), self-chosen: L
- 2026-11-08 Stage 2: pass — r1 fixes: CR-1..CR-8 each with a failing test first; all ACs green; test step fails only on baseline evals
- 2026-11-08 Stage 2: pass — T-1 fixed test-first; all ACs green; test step fails only on baseline evals
- 2026-11-08 Stage 3: pass — review r2 PASS; T-1 fixed with a test
- 2026-11-08 after ship commit d00ba7a: added TestRemainingMessages/TestRunHttpMessages so every error message in contracts.py has a test (spec Acceptance); it found one gap, a '? key' line not naming complex keys, fixed in contracts.py (_Block.mapping). Not re-reviewed: a 2-line change, its test seen failing then passing. verify: only baseline evals fail.

## Deviations
- 2026-11-08 Public Surface What: contracts.py's module functions (check_id, check_criteria, check_story, check_lock, check_bundle, check_http_test, run_http, check_departures, check_finding, finding_route, check_cost, sum_cost, parse_yaml, schema_errors, criterion_text_sha256, header_for, vendor_check, run_fixtures, seal, main) and the eval's helpers (append, check, tampered, strip_header_and_reseal) are top-level names, listed only as 'command contracts.py' in the plan. Why: the plan named the CLI; the test file imports these functions to test each rule directly. Effect: none on consumers, who call the CLI; the functions are importable for the unit tests.
- 2026-11-08 Fixture files and exception classes What: the plan named the folder contracts/v1/fixtures/ and the module contracts.py; the files under it are contracts/v1/fixtures/bundle/invalid/sha256-mismatch/http/F-ISS-01.AC2.yaml contracts/v1/fixtures/bundle/invalid/sha256-mismatch/manifest.json contracts/v1/fixtures/bundle/invalid/sha256-mismatch/seed/team-eng-11-issues.yaml contracts/v1/fixtures/bundle/invalid/url-in-test/http/F-ISS-01.AC2.yaml contracts/v1/fixtures/bundle/invalid/url-in-test/manifest.json contracts/v1/fixtures/bundle/invalid/url-in-test/seed/team-eng-11-issues.yaml contracts/v1/fixtures/bundle/valid/trackr/http/F-ISS-01.AC2.yaml contracts/v1/fixtures/bundle/valid/trackr/manifest.json contracts/v1/fixtures/bundle/valid/trackr/seed/team-eng-11-issues.yaml contracts/v1/fixtures/cost/invalid/negative-wall-s.jsonl contracts/v1/fixtures/cost/valid/cost.jsonl contracts/v1/fixtures/departures/invalid/no-decided-by.yaml contracts/v1/fixtures/departures/invalid/proposed-blocks.yaml contracts/v1/fixtures/departures/valid/departures.yaml contracts/v1/fixtures/finding/invalid/no-verified-by.json contracts/v1/fixtures/finding/invalid/route-mismatch.json contracts/v1/fixtures/finding/valid/BH-0007.json contracts/v1/fixtures/finding/valid/BH-0008-not-reproduced.json contracts/v1/fixtures/http/invalid/capture-used-before-taken.yaml contracts/v1/fixtures/http/invalid/no-steps.yaml contracts/v1/fixtures/http/valid/F-ISS-01.AC2.yaml contracts/v1/fixtures/lock/invalid/level-2-without-test.json contracts/v1/fixtures/lock/invalid/tag-with-brackets.json contracts/v1/fixtures/lock/valid/trackr/criteria.lock.json contracts/v1/fixtures/yaml/invalid/anchor.yaml contracts/v1/fixtures/yaml/invalid/block-scalar.yaml contracts/v1/fixtures/yaml/invalid/duplicate-key.yaml contracts/v1/fixtures/yaml/valid/scalars.yaml  and the module also exports the exceptions YamlError and SchemaUnsupported. Why: a file per valid and invalid example of each artifact, as the spec's Acceptance asks; the exceptions are how parse and schema failures surface. Effect: none beyond the plan; every fixture is in MANIFEST.
- 2026-11-08 Review r1 fixtures What: added contracts/v1/fixtures/bundle/invalid/seed-outside-bundle/http/F-ISS-01.AC2.yaml contracts/v1/fixtures/bundle/invalid/seed-outside-bundle/manifest.json contracts/v1/fixtures/bundle/invalid/seed-outside-bundle/seed/team-eng-11-issues.yaml contracts/v1/fixtures/http/invalid/json-not-a-list.yaml contracts/v1/fixtures/yaml/invalid/empty-key.yaml contracts/v1/fixtures/yaml/invalid/unclosed-flow-value.yaml. Why: code review r1 (CR-1, CR-2, CR-3) asked for an invalid fixture per crash and escape it found, so every consumer's vendor-check covers them. Effect: four more invalid fixtures in MANIFEST.

## Open questions
-
