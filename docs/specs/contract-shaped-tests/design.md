# Contract-shaped recorded tests, proven through a reference adapter

Status: proposed, 2026-11-16. Answers issue #9 item 6; direction chosen by the user ("contract tests + adapter").

## The problem

rspec records each acceptance test against the running reference, in the reference's own API: Twenty's GraphQL
`/metadata` and `/graphql`, `/object/<name>/<id>`. A rebuild whose Gate 3 locks a different API (the CRM's REST
contract, `openapi.json`) can never pass those tests. In the CRM rebuild every slice then reduced G6's open and
hidden suites to a departure plus builder tests: the reference stopped being the oracle for every API criterion.

## The idea

Write the tests in the locked contract's terms, and prove them on the reference through an **adapter**: a small
HTTP service that serves the locked contract and answers each call by calling the reference's own API.

```
rspec:verify      test (contract-shaped) ──> adapter ──> reference      proves the test (level 2)
G5 lanes, G6      test (contract-shaped) ──────────────> rebuild        nothing in between
```

The adapter sits only on the reference side. A bug in it makes a test fail at verify, where rspec's verify-judge
already handles a disputed criterion. It can never hide a build bug, because the build runs the tests directly.
The rejected alternative put an adapter in front of the build, where a translation bug could pass a broken build
at every boundary.

## What changes

**product-rebuild (owns the adapter, because it spans the spec and the build)**

1. **When it applies.** After Gate 3, `rebuild-pipeline` compares the locked contract with the reference's API.
   When the rebuild keeps the reference's API (`target_shape: client-only`, or a contract transcribed from it),
   nothing changes. When the contract is new, `sources.yaml` records `reference.adapter: required`, and verify
   waits for the adapter.
2. **Building it.** It is an sdlc feature in the workbench (`adapter/`), built against the locked `openapi.json`.
   Each operation the MVP criteria use maps to reference calls, and its own tests run against the live reference.
   It is a **pass-through**: every response it returns comes from a reference call in that request, and it keeps
   no state of its own. It logs each request with the reference calls it made.
3. **Trusting it.** A check, `adapter.py audit`, replays verify's recorded traffic. It fails on any adapter
   response that no reference call backs, which stops an adapter that answers by itself and so would make the
   tests pass against nothing. Gate 4 records the adapter's source hash beside the bundle, so it can't change
   unseen after the tests are proven.
4. **Unchanged.** G5 and G6 work as before: `ACCEPT_BASE_URL` points at the build, and the tests and seeds are
   contract-shaped, so lanes, the hidden suite, equivalence and bug-hunter run them as they are. A departure goes
   back to what it's for: a deliberate difference in behaviour, not in API shape.

**rspec (only takes an adapter URL)**

5. `rspec.json` `reference.run.adapter`: `{start, base_url}`. When set, verify starts it after the reference and
   points `base_url_env` at the adapter, not the reference.
6. The criterion-recorder and reference-seeder already read `<contracts>/openapi.json`. When an adapter is set,
   every request path and seed step must be an operation in it, and a reference-native path is refused.
   `verify_report.py` reports a criterion that needs an operation the adapter doesn't map as `unrecordable`, with
   the reason (no new outcome type).

## Out of scope (open questions)

- **UI (Playwright) criteria.** The rebuild's UI isn't the reference's UI either, so routes and selectors differ.
  An adapter can't map a page. Options: tests written against accessible roles and text, recorded against the
  reference and run against the build, with routes taken from the locked UI map; or keep the departure plus
  builder tests for UI. To decide separately.
- **Writes the reference can't express.** A contract operation with no reference equivalent becomes an
  `unrecordable` criterion with a builder test, as today's level 1.

## Moving the CRM rebuild

S1 to S4 already have reference-shaped tests and their departures. For S5 on, build the adapter, re-record the
remaining slices' criteria with `rspec:verify --only <features>` through it, and reopen and relock Gate 4 for the
new bundle. Shipped slices keep their departures. Re-recording them is optional and goes slice by slice.

## Build order

1. rspec: `reference.run.adapter` and the recorder and seeder rule (small; one release).
2. product-rebuild: the post-Gate-3 check, the adapter feature's brief, `adapter.py audit`, and Gate 4 recording
   the adapter hash.
3. CRM: build its adapter, then re-record from S5.
