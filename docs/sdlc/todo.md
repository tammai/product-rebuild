# Todo

## Open

- [ ] reference_guard.py writes no log, but 06-rollout's E2E pass condition names guard logs: either log each denial (append-only, in the workbench's logs/) or change 06 to name transcript evidence — E2E-1 uses transcript evidence through its harness guard_check.py meanwhile; feature 2026-11-08-l-product-rebuild-3 (2026-11-09)
- [ ] CR-1: protect departures appended after Gate 1 as well (record each later entry, e.g. on append, so editing or removing one fails validate.py), today only the entries present at the gate-1 lock are protected — the user shipped 3.0.0 with the spec's literal rule (05 Gate 1 row, "records the IDs present at its lock"); skills/rebuild-pipeline/scripts/departures.py, feature 2026-11-09-m-departures-append-known-gap (2026-11-09)
- [ ] CR-14: read locks/gate-1.yaml and docs/departures.yaml once per departures.append() instead of up to three and two times — redundant I/O only, not a bug; skills/rebuild-pipeline/scripts/departures.py, feature 2026-11-09-m-departures-append-known-gap (2026-11-09)
- [ ] R2-7: read gate-1's departures_at_lock with yamlio instead of departures.recorded()'s line regex, dropping the coupling that makes record() restrict IDs to D-<nnn> so they read back — the ID rule keeps writer and reader in step meanwhile; skills/rebuild-pipeline/scripts/departures.py and gate.py, feature 2026-11-09-m-departures-append-known-gap (2026-11-09)
- [ ] R2-9: give every _lock_gateN_checks the same (gid, argv) -> (rc, extra) signature so cmd_lock has one dispatch loop and _lock_gate1_checks no unused argv — style only; skills/rebuild-pipeline/scripts/gate.py, feature 2026-11-09-m-departures-append-known-gap (2026-11-09)
- [ ] Re-render docs/img/pipeline.png from docs/img/pipeline.html, whose Gate 1 box now reads "features.md · domain.md (departures.yaml append-only)" — needs a browser render, not done in the change; feature 2026-11-09-m-departures-append-known-gap (2026-11-09)

## Done
