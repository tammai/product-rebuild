# Part plan: product-rebuild 3.0.0 B5

**Record:** [docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md](../../../docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md) · **Backlog:** [backlog.md](backlog.md)

## Tasks

1. **Gate 5 and goal production** — AC-010
   - Files: `skills/rebuild-pipeline/scripts/gate.py`, `skills/rebuild-pipeline/scripts/rebuild_init.py`
   - Test first: `eval/gp_eval.py gate5`.
   - Then: gate-5 refusals (readiness, NFR evidence, hidden suites, equivalence, high findings, proposed departures, MVP level 0); gate-5 protects `docs/production-readiness.md` and `parity/gp/nfr-evidence.md`; gate-1 refuses a goal other than production.
2. **GP's NFR evidence** — AC-023
   - Files: `skills/rebuild-pipeline/scripts/gp.py` (new)
   - Test first: `eval/gp_eval.py nfr`.
3. **Budgets** — AC-024
   - Files: `skills/rebuild-pipeline/scripts/rebuild_init.py`, `skills/rebuild-pipeline/scripts/route.py`, `skills/rebuild-pipeline/scripts/boundary.py`
   - Test first: `eval/gp_eval.py budgets`.
4. **Cost logs** — AC-025
   - Files: `skills/rebuild-pipeline/scripts/cost.py` (new), `skills/rebuild-pipeline/scripts/boundary.py`
   - Test first: `eval/gp_eval.py cost`.
5. **Autopilot parking** — AC-026
   - Files: `skills/rebuild-pipeline/scripts/autopilot.py`, `skills/rebuild-pipeline/references/autopilot.md`
   - Test first: `eval/gp_eval.py park`.
6. **The rspec template PR and docs** — AC-027
   - Files: `docs/rspec-pr/production-readiness.md`, `docs/rspec-pr/PR.md`, `skills/rebuild-pipeline/references/gp-production.md`, `skills/rebuild-pipeline/SKILL.md`, `CHANGELOG.md`

## Public Surface

- command `gp.py nfr|check` — AC-023
- command `cost.py add` — AC-025
- command `autopilot.py park|unpark|blocked` — AC-026
- config `rebuild.yaml budgets.*` — AC-024
