# Part plan: product-rebuild 3.0.0 B6

**Record:** [docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md](../../../docs/sdlc/changes/2026-11-08-l-product-rebuild-3.md) · **Backlog:** [backlog.md](backlog.md)

Runs after B7 (the coverage port), so every capability has a working owner before a 2.x part is deleted (05 P1).

## Tasks

1. **The capability table** — AC-011
   - Files: `docs/MIGRATION-3.md`, `skills/rebuild-pipeline/eval/migration_3.py` (new)
   - Test first: `eval/migration_3.py`; `--external` against the local rspec, sdlc and bug-hunter checkouts, once.
   - Proofs this repo owns that had no passing group: `lane_guards.py` and `run_supervision.py` gain named
     groups (and `lane_guards.py runbook`), `g6_eval.py remine`, `lanes_rspec.py archive`, `lane_plan.py
     worker|routing|approval`, `gate_status.py`'s preflight checks.
2. **The rspec template PR for lane R's recall fixture** — row 9 of the table
   - Files: `docs/rspec-pr/rules-recall/` (the moved fixture and `PR.md`)
3. **adr/ for the vendored playbook and its scaffold manifest** — AC-031 (coordinator pr-6, the second question)
   - Files: `skills/rebuild-pipeline/scripts/playbook.py` (`vendor`), `gate.py` (gate-3), `rebuild_init.py`,
     `validate.py`
   - Test first: `eval/gates_rspec.py scaffold`.
4. **Deletions** — the five mining agents, their references and rubrics, lane R, the judge's scripts, `erd.py`,
   `basis.py`, the 2.x schemas, `lane_plan.py --specs`, the 2.x scaffold folders, the evals and fixtures that
   tested them; the knock-ons in `validate.py`, `parity.py`, `acsuite.py`, `routing.py`, `rebuild_init.py`.
5. **Docs** — `README.md`, `docs/PLAYBOOK.md`, `docs/img/pipeline.html` and `.png`, `SKILL.md`, the phase
   references, `agents/lane-worker.md`, the playbooks' notes, `CHANGELOG.md`, `CLAUDE.md` (the lane R evals rule
   goes), `.sdlc/baseline.md` (the `rules_recall.py` row goes with the eval).

## Public Surface

- command `playbook.py vendor` — AC-031
- config `locks/gate-3.yaml protects: adr/` — AC-031
- removed: `lane_plan.py --specs`/`--amend`, `playbook.py excerpt`, `rules_for.py`, `cite_excerpts.py`,
  `gate_facts.py`, `evidence_bundle.py`, `erd.py`, `basis.py`, the routing roles `miner`, `spec-writer`,
  `data-model-drafter`, `adr-drafter`, `rubric-judge` (05 D2, D3; breaking, as 3.0.0 is)
