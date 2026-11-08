# PR to rspec: one production-readiness checklist (product-rebuild 3.0, spec 05 P8)

**For:** the rspec worker, to apply to `templates/production-readiness.md` in tammai/rspec (branch of the rspec 0.11
line). Written in product-rebuild because product-rebuild's workers do not edit rspec; the coordinator dispatches it.

## Why

Spec 05 P8: "One checklist: rspec's `production-readiness.md` (goal `production` is forced in a rebuild). GP's own
list merges into rspec's template (PR to rspec), so there is one source." product-rebuild 3.0 now reads only rspec's
file in the workbench (`docs/production-readiness.md`), and its Gate 5 refuses while an item is unchecked. Items
only product-rebuild's 2.x GP list had would otherwise be lost.

## What changes

The proposed template is [production-readiness.md](production-readiness.md) beside this file: rspec's template
with GP's items added. Nothing of rspec's is removed or reworded except where a GP item makes it sharper (noted).

| Section | Added from GP | Note |
|---|---|---|
| (intro) | "A drill is performed, not described: name who did it and when." | GP: evidence, not assertion |
| Security | authorization reviewed against domain.md's permissions table; container scanning; rate limits and input validation tested | the authz line replaces rspec's "Authorization tests for every role and tenant boundary", keeping it |
| Performance | load test run against the production candidate | sharpened |
| Requirements (NFRs) | new: every NFR's stated Verification run against the production candidate, evidence linked | P8's "GP adds execution"; product-rebuild's `gp.py` keeps the per-NFR record |
| Reliability | automated backups split from the drill; restore into a clean environment, data verified; one migration rollback exercised | |
| Observability | "is it up, erroring, slow" answerable without shell access | |
| Operations | one-command deploy; rollback rehearsed; upgrade path; top-three failure runbook; incident dry run by a person | |
| Documentation | new: install guide for a stranger; architecture doc matches accepted ADRs | |
| Parity with the reference | new, deletable: equivalence traces and hidden tests green on the production candidate or a decided departure | P8's Gate 5 conditions, so the checklist and the gate agree |
| Client app | new, deletable: GP's client-app checklist | GP's second checklist, for anything shipped to a device |

## Acceptance

- `rspec_lib.readiness_open()` still parses the file (`## Category` + `- [ ] item`); the deletable sections follow the
  existing "Cutover … delete this section" convention.
- rspec's `progress.py` keeps reporting `readiness` as pending while any item is unchecked.
- No rspec test asserts the old item text (the rspec worker checks with its suite).
