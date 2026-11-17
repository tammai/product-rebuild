# upgrade.py prefers the backslash manifest key when a file has both

## Why

**Request (verbatim):** "Fix dup keys, then 3.3.1" — when a manifest holds both the `/` and `\` key for a file, prefer the `\` one (only the buggy writer made it, always later), not whichever comes last in the JSON.

The Kanso CRM workbench's `locks/tooling.json` holds `scripts/boundary.py` (the 3.2.0 hash) and `scripts\boundary.py` (the 3.2.1 hash an older `--apply` wrote on Windows). 2026-11-17-m-crm-lane-upgrade-fixes folds both to `/` and keeps whichever comes later in the JSON, so the right answer depends on key order. Reversed, a pristine copy reads as LOCALLY MODIFIED and is refused (safe, but wrong).

## Decisions

| Decision | Ruled out | Why |
|---|---|---|
| A backslash key wins over its forward-slash twin | the key whose hash matches the file on disk | only the buggy writer made `\` keys, always after the `/` one (rebuild_init writes `/` at scaffold time), so `\` is the newer record; matching the disk would turn a real local edit's old record into "stale" |

## Acceptance criteria

- **AC-001** Given a manifest with both `scripts\flows.py` (the current hash) and, later in the JSON, `scripts/flows.py` (an old hash), when upgrade.py runs, then the file is STALE, not LOCALLY MODIFIED.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | skills/rebuild-pipeline/eval/upgrade_manifest_keys.py › with both key forms for one file, the backslash one is the record | `python3 skills/rebuild-pipeline/eval/upgrade_manifest_keys.py` |

## Must never break

- upgrade.py never copies over a file edited here without `--force`.

## Out of scope

- Other #16 tickets.

## Review

No review ran: no trigger fired.
