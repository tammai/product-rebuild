# Part plan: product-rebuild 3.0.0 B3

**Record:** [docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md](../../../docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md) · **Backlog:** [backlog.md](backlog.md)

## Tasks

1. **Holdout split and the Gate 4 record** — AC-007
   - Files: `skills/rebuild-pipeline/scripts/holdout.py` (new), `skills/rebuild-pipeline/scripts/gate.py`
   - Test first: `eval/holdout_eval.py split`.
   - Then: per build-plan slice, D4 selection from a seed, files moved to `<project>-holdout/` (git), manifest `visibility: hidden`, `plan/holdout.json`; refuse when a listed repo contains or references the holdout; gate-4 refuses until the record matches the manifest, then writes `holdout:` into the lock.
2. **Holdout run** — AC-015
   - Files: `skills/rebuild-pipeline/scripts/holdout.py`
   - Test first: `eval/holdout_eval.py run`.
   - Then: http through `contracts.py run-http` (plugin found by `.rebuild-plugin` or `--contracts`), Playwright through the code repo's `node_modules/@playwright/test/cli.js`, Maestro through `maestro test`, cli not run; `parity/holdout/<Sn>.json` and `.md` with observed behaviour only.
3. **Lanes from rspec's slices** — AC-016, AC-017, AC-018
   - Files: `skills/rebuild-pipeline/scripts/lane_plan.py`
   - Test first: `eval/lanes_rspec.py lane`, `step0`, `questions`.
   - Then: `--features` mode (criteria from the lock, cited ACs, `--criteria`), the lane's open bundle and lock copy with sha256 checks, `refresh`, `step0`, `questions`, the lane cap.
4. **Flow guard over the bundle** — AC-008
   - Files: `hooks/scripts/flows_guard.py`, `skills/rebuild-pipeline/scripts/flows.py`, `skills/rebuild-pipeline/scripts/rebuild_init.py`
   - Test first: `eval/lanes_rspec.py flows`.
   - Then: a `docs/acceptance` suite in the guard; `flows.py unlock|relock|status --acceptance`; its unlock file git-ignored.
5. **Docs** — AC-016
   - Files: `skills/rebuild-pipeline/SKILL.md`, `skills/rebuild-pipeline/references/g5-build.md`, `CHANGELOG.md`
   - Then: the slice loop's step 0, lanes, spec questions and the holdout split before Gate 4.

## Public Surface

- command `holdout.py split|run` — AC-007
- command `lane_plan.py step0|questions|refresh, --features` — AC-016
- command `flows.py unlock|relock|status --acceptance` — AC-008
- config `rebuild.yaml budgets.parallel_lanes` — AC-016
