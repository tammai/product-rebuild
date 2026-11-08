# Backlog: 2026-11-08-l-product-rebuild-3

Record: the feature's change file (`scaffold.py paths <feature>` → `change`) · Branch: `2026-11-08-l-product-rebuild-3` · Each slice gets a short `plan-B<n>.md` when it starts and ends as one commit on the branch.

| ID | Slice | FRs | ACs | Deps | Size | Status |
|---|---|---|---|---|---|---|
| B1 | Dependencies, posture field, P3 guard, refusal of 2.x workbenches | Decisions, P3, D7 | 1, 2, 3, 4, 5 | — | M | done |
| B2 | P2 wiring: skill calls rspec stages, gate locks on rspec artifacts, `progress.py` integration | P2 | 6, 12, 13, 14 | B1 | M | done |
| B3 | P4 holdout; P5 slice loop changes, generalised flow guard | P4, P5 | 7, 8 | B2 | M | todo |
| B4 | P6 G6 sequence, `route.py`, human sample; P7 registry migration in scripts | P6, P7 | 9 | B3 | M | todo |
| B5 | P8 GP changes (and the rspec template PR); P9; P10 | P8, P9, P10 | 10 | B4 | M | todo |
| B6 | P1 capability table, then deletions; docs (README, PLAYBOOK, pipeline image) | P1 | 11 | B5 | M | todo |
