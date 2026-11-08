# Hidden tests live outside the project, not behind a longer denylist

Decided 2026-11-09 (3.0.0 part 6, redesign R1, after two review rounds failed in the reference guard).

- The holdout is a git repo in the per-user data folder (`hooklib.rebuild_data_dir`: `$PRODUCT_REBUILD_DATA`,
  else `%LOCALAPPDATA%` or `$XDG_DATA_HOME`, then `product-rebuild/holdouts/<project>-<random hex>`), named
  only in that folder's `holdouts.json`. No workbench file and no lane brief names it.
- `reference_guard.py` denies that whole folder, every configured holdout, and the rc-era
  `<parent>/<project>-holdout`. It fails closed when a folder has `locks/` beside repos.yaml or sources.yaml
  but no readable `rebuild_major` marker.
- The guard's command lists (`RECURSIVE`, `WRITERS`, `GIT_WRITES`) are frozen. Two rounds each found more
  unlisted readers, writers, nested shells and Windows short names. Those are documented limits (README,
  MIGRATION-3.md), not findings to patch. A new review finding of that shape goes to the user, not into the list.

**Why:** a guard is the second line. The first line is never handing a lane the path at all.

**How to apply:** a feature that needs a lane to see something new extends what the lane is given, never the
guard's enumeration. Code that locates the holdout reads the config (`holdout.holdout_dir()`, a copy of the
hooklib reader; change both together) and refuses when there is no entry. It never falls back to a path
derived from the project name.
