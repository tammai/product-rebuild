# Part plan: product-rebuild 3.0.0 B2

**Record:** [docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md](../../../docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md) · **Backlog:** [backlog.md](backlog.md)

## Tasks

1. **Gates on rspec's artifacts, in rspec's order** — AC-006
   - Files: `skills/rebuild-pipeline/scripts/gate.py`, `skills/rebuild-pipeline/scripts/rebuild_init.py`, `skills/rebuild-pipeline/scripts/validate.py`
   - Test first: `eval/gates_rspec.py order`.
   - Then: ORDER 1, 3, 2, 4, 5; new protects; gate-1 stage check, gate-3 ADR status in `docs/decisions/`, gate-2 audit/verify check; drop the playbook and data-model lock checks and validate.py's "fatal once locked" clauses for them.
2. **Gate 4's level 2 floor** — AC-012
   - Files: `skills/rebuild-pipeline/scripts/gate.py`
   - Test first: `eval/gates_rspec.py level2`.
   - Then: share from `criteria.lock.json`, posture from `sources.yaml`, `--accept-level2` writes `level2_waiver` into the lock.
3. **rspec's progress in status** — AC-013
   - Files: `skills/rebuild-pipeline/scripts/gate.py`
   - Test first: `eval/gates_rspec.py progress`.
   - Then: find rspec (`$RSPEC_PLUGIN_ROOT`, else installed_plugins.json), run its progress.py on `docs`, print one line, or `not run: <reason>`.
4. **Skill routing** — AC-014
   - Files: `skills/rebuild-pipeline/SKILL.md`, `CHANGELOG.md`
   - Test first: manual.
   - Then: the phase table in P2's order, each step naming the rspec stage or gate; the stack preference step before `rspec:tech`.
5. **Evals that assumed the 2.x gates** — AC-006
   - Files: `skills/rebuild-pipeline/eval/gate_status.py` and any other eval that locks a 2.x gate path
   - Then: move their cases to the 3.x gates, drop cases for behaviour P2 removed (G1 mining phase, adr/ proposals).

## Public Surface

- command `gate.py lock gate-4 --accept-level2 <reason>` — AC-012
- env `RSPEC_PLUGIN_ROOT` — AC-013
