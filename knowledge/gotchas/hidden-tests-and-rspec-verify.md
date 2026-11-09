# rspec:verify drops the hidden entries; git history checks must use blob ids

- **rspec:verify rebuilds `docs/acceptance/manifest.json`** from its own runs and levels, with only level-2
  open tests. After the split those no longer include the hidden criteria, so every amend's re-verify drops
  them. Anything that reads the manifest for lanes or gates calls `holdout.reconcile()` first:
  `lane_plan.py` open, refresh and step0, `boundary.py`, and gate-4's lock. Copying to a lane also filters by
  `plan/holdout.json`'s `hidden` list, not by the manifest's `visibility`. A step that skipped reconcile once
  sent `rspec:verify --only` to re-record exactly the hidden criteria as open tests.
- **"Is this file in git's history" means its blob, not its path.** `git log --all -- <path>` misses the
  reflog and loose objects a rewrite leaves behind. Use `git hash-object` plus `git cat-file -e`, and try both
  the filtered and the `--no-filters` id: with `core.autocrlf` on (this machine), they differ.
- **Evals set `PRODUCT_REBUILD_DATA` to a temp folder** before anything runs `holdout.py`. Without it a run
  writes into the real `%LOCALAPPDATA%\product-rebuild`.
