# Part plan: product-rebuild 3.0.0 B7

**Record:** [docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md](../../../docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md) · **Backlog:** [backlog.md](backlog.md)

Split from B6 (coordinator pr-6 Q1 a), and run before it: 05 P1 places each 2.x capability with a working
3.0 owner before any 2.x part is deleted, and G6 step 4 still read the 2.x `matrix/features.yaml` and
`plan/slices.yaml`.

## Tasks

1. **Slices and features from rspec** — AC-028, AC-029
   - Files: `skills/rebuild-pipeline/scripts/sequence.py` (`plan_slices`, `plan_features`: slices from
     `docs/build-plan.md`, a slice's dependencies from its stories' `depends_on` in `docs/features/`, features
     and priorities from `docs/features.md`), `skills/rebuild-pipeline/scripts/parity.py`,
     `skills/rebuild-pipeline/scripts/slice_review.py`, `skills/rebuild-pipeline/scripts/gate.py`
   - Test first: `eval/coverage_rspec.py reports`, `eval/coverage_rspec.py order`.
2. **Step 4 not run** — AC-030
   - Files: `skills/rebuild-pipeline/scripts/boundary.py`
   - Test first: `eval/coverage_rspec.py notrun`.
3. **Evals on the 2.x inputs** — no new AC
   - Files: `eval/dates_and_reruns.py`, `eval/run_supervision.py`, `eval/windows_and_upgrade.py`,
     `eval/gate_status.py` move their fixtures to `docs/features.md` and `docs/build-plan.md`.

## Public Surface

- none: the commands and their output files are unchanged; only what they read moved to rspec's artifacts.
