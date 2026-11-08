# Part plan: product-rebuild 3.0.0 B1

**Record:** [docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md](../../../docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md) · **Backlog:** [backlog.md](backlog.md)

## Tasks

1. **Dependencies and version** — AC-001
   - Files: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md`
   - Test first: manual (configuration values), checked in review.
   - Then: add rspec and bug-hunter, move sdlc and sdlc-extras to `>=3.5.0-rc.6 <4`, version `3.0.0-rc.1`, allow the three marketplaces.
2. **Posture field** — AC-002
   - Files: `skills/rebuild-pipeline/scripts/rebuild_init.py`, `skills/rebuild-pipeline/scripts/validate.py`, `skills/rebuild-pipeline/references/g0-reference.md`
   - Test first: `eval/reference_guard.py posture`.
   - Then: `posture:` in the sources.yaml template; validate.py fails on an unknown value, warns on own-code with a third-party kind; G0 asks for it.
3. **P3 guard** — AC-003, AC-004
   - Files: `hooks/scripts/reference_guard.py`, `hooks/scripts/hooklib.py`, `hooks/hooks.json`, `README.md`
   - Test first: `eval/reference_guard.py reference` and `holdout`.
   - Then: a PreToolUse guard on Read|Grep|Glob|Bash for lane calls, denying the reference (unless own-code) and the holdout; README says it is a guard, not a sandbox.
4. **Refuse 2.x workbenches** — AC-005
   - Files: `hooks/scripts/hooklib.py`, `skills/rebuild-pipeline/scripts/rebuild_init.py`, `skills/rebuild-pipeline/scripts/upgrade.py`, `skills/scaffold-repo/scripts/scaffold.py`, `skills/rebuild-pipeline/SKILL.md`, `commands/rebuild.md`, `docs/PLAYBOOK.md`, evals `v0_fence.py`, `lane_guards.py`, `scaffold_repo.py`
   - Test first: `eval/v0_fence.py`.
   - Then: marker 3 everywhere it is written or read; the refusal names 2.2.0.

## Public Surface

- config `sources.yaml reference.posture` — AC-002
- dependency `rspec >=0.11.0-rc.1 <1` — AC-001
- dependency `bug-hunter >=0.4.0-rc.1 <1` — AC-001
