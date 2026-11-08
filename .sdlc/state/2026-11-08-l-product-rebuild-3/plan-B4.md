# Part plan: product-rebuild 3.0.0 B4

**Record:** [docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md](../../../docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md) · **Backlog:** [backlog.md](backlog.md)

## Tasks

1. **One departures registry** — AC-021
   - Files: `skills/rebuild-pipeline/scripts/departures.py` (new), `skills/rebuild-pipeline/scripts/holdout.py`, `skills/rebuild-pipeline/scripts/equiv.py`, `skills/rebuild-pipeline/scripts/flows.py`, `skills/rebuild-pipeline/scripts/gate.py`, `skills/rebuild-pipeline/scripts/rebuild_init.py`
   - Test first: `eval/g6_eval.py departures`.
   - Then: load/explain/append in one module, the gate-1 rule in one function; holdout `explained`; `equiv.py accept` and `flows.py unlock --weakens` append; gate-5 reads departures; equivalence applies by posture.
2. **route.py** — AC-009
   - Files: `skills/rebuild-pipeline/scripts/route.py` (new)
   - Test first: `eval/g6_eval.py route`.
   - Then: findings from `parity/findings/<Sn>/` and the holdout repo, contracts C6 checks through the plugin's contracts.py, rounds in `plan/fix-rounds/<Sn>.json`, `--close`.
3. **The G6 sequence and the human sample** — AC-019, AC-020
   - Files: `skills/rebuild-pipeline/scripts/boundary.py`, `skills/rebuild-pipeline/scripts/slice_review.py`
   - Test first: `eval/g6_eval.py boundary`, `sample`.
   - Then: steps in P6's order with the re-run, findings for what still fails, the stop rule, `hunted`, `sample`; slice_review keeps the `## Human sample` section.
4. **Fix lanes** — AC-022
   - Files: `skills/rebuild-pipeline/scripts/lane_plan.py`
   - Test first: `eval/g6_eval.py fix`.
   - Then: `--fix <round> --findings <ids>`.
5. **Docs** — AC-019
   - Files: `skills/rebuild-pipeline/SKILL.md`, `CHANGELOG.md`

## Public Surface

- command `route.py <Sn> [--close <ids>]` — AC-009
- command `boundary.py <Sn> | sample <Sn> | hunted <Sn>` — AC-019
- command `lane_plan.py --fix <round> --findings <ids>` — AC-022
- command `flows.py unlock --weakens --criteria <ids>` — AC-021
