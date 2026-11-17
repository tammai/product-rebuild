# Fix lane, lane folder and upgrade-key bugs from the CRM S1–S4 report

## Why

**Request (verbatim):** Fix four pipeline bugs from the CRM rebuild S1–S4 report (C:/Users/Admin/orca/projects/crm-rebuild-sdlc/crm-workbench/plan/drafts/product-rebuild-issues-S1-S4.md): (4b) upgrade.py looks up locks/tooling.json keys with os.sep paths while the lock stores '/', so on Windows edited files show as unknown provenance instead of local edits — normalise files/kept keys to '/' on read and write; (4a) lane_plan.py --fix refuses findings for an earlier slice's feature ('not in S3 of build-plan.md') — in fix mode accept features of this or any earlier slice; (4f) lane_plan.py rmtree's the lane's acceptance/ and shows deletions of earlier features' specs — replace only the lane's own specs; (5c) acsuite.py parity files keyed by date only collide when two slices run the same day — add the slice id to the name, keeping the date. One failing test per bug. Fix 4b first.

The Kanso CRM rebuild hit these three on every slice and worked around each by hand. 4b also blocks that workbench's clean upgrade to the 3.2.1 boundary fix, since its local patches and stale copies all look alike.

**The user's words:** 5c is split out to its own follow-up: its date-only name is read by seven scripts and two docs ("Split it out"). 4i (the Bash guard reading a later `rm -f` as a force push) was added once the CRM session sent the exact command ("Add to this PR"), then dropped after review round 7 ("Drop 4i, ship the rest"): every way of splitting the pre-tokenizer backstop let through force pushes it blocked before, the last ones through `xargs` in a loop, function or background list. It goes to #16 for a fix in the tokenizer's `verdict()`.

## Decisions

| Decision | Ruled out | Why |
|---|---|---|
| 4b: manifest keys are compared and written with `/`; keys read from disk are normalised, so a backslash-keyed manifest an older upgrade.py wrote on Windows still matches | changing how `rel` is built for file operations | file I/O works with native paths; only the manifest key is the contract |
| 4a: a fix lane accepts a feature of its own slice or any earlier one | skipping the check for fix lanes | a feature of a slice not built yet has no code to fix |
| 4f: the lane's acceptance/ is still rebuilt whole, but from the open tests of every feature up to the lane's slice; earlier specs come back byte-identical, so the diff shows no deletions | no wipe, with selective clean-up (review rounds 1–2) | selective clean-up left hidden-test files, moved tests, old seeds and orphaned support files behind (6 highs); rebuilding whole keeps "no hidden test reaches a lane" by construction, and parallel lanes of a slice write identical manifests |

**Bug:** 4b: `upgrade.py` builds `rel` with `os.path.normpath`, so on Windows `baseline.get("scripts\\flows.py")` misses the `scripts/flows.py` key rebuild_init.py wrote and the file is `unknown`; `--keep` and `--apply` then write backslash keys. 4a: `lane_plan.py` checks every feature against the current slice only, in fix mode too. 4f: `copy_to_lane` rebuilds the lane's `acceptance/` from the lane's own tests only. Each is shown by its AC's test failing on Base.

## Acceptance criteria

- **AC-001** Given a workbench whose vendored script was edited locally, when upgrade.py runs, then the file is listed LOCALLY MODIFIED (not UNKNOWN PROVENANCE), with forward-slash or backslash manifest keys, and `--keep` records it under a forward-slash key that the next run reports KEPT.
- **AC-002** Given slice S2's hunt routed a build-defect in a feature slice S1 built, when `lane_plan.py S2 <lane> --fix 1 --findings <id>` runs, then the fix lane opens.
- **AC-003** Given a routed finding in a feature of a later slice, when a fix lane is opened for it, then it is refused, naming the feature.
- **AC-004** Given open tests of other features up to the lane's slice, when lane_plan opens or refreshes a lane, then its acceptance/ and manifest hold them unchanged beside the lane's own, and a copy of the lane's own test the bundle has moved, or a seed file the bundle no longer has, is gone.
- **AC-005** Given a hidden test's file is in a lane's acceptance/, when lane_plan copies or refreshes, then the file is removed; an open test whose file is also a hidden criterion's is refused, nothing copied.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | skills/rebuild-pipeline/eval/upgrade_manifest_keys.py | `python3 skills/rebuild-pipeline/eval/upgrade_manifest_keys.py` |
| AC-002 | skills/rebuild-pipeline/eval/g6_eval.py › a fix lane opens for a finding in a feature an earlier slice built | `python3 skills/rebuild-pipeline/eval/g6_eval.py fix` |
| AC-003 | skills/rebuild-pipeline/eval/g6_eval.py › …and is refused for a feature of a later slice | `python3 skills/rebuild-pipeline/eval/g6_eval.py fix` |
| AC-004 | skills/rebuild-pipeline/eval/lanes_rspec.py › a lane's acceptance/ also holds the open tests of the other features up to its slice | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py lane` |
| AC-005 | skills/rebuild-pipeline/eval/lanes_rspec.py › a refresh removes a hidden test's file from the lane | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py lane` |

## Must never break

- No hidden test ever reaches a lane.
- upgrade.py never copies over a file edited here without `--force`.
- A normal (non-fix) lane still opens only for features of its own slice.

## Out of scope

- 4i (Bash guard false positive on a later `rm -f`): dropped after review round 7, to #16.
- 5c (same-day parity files collide): its own follow-up feature.
- The report's design items (#2, #3, 5a, 5b, 5d, 5e, #6), rspec's 4h, and 4g (needs a repro): filed as https://github.com/tammai/product-rebuild/issues/16.

## Review

**What fired and why.** No table row fired (low risk, Public Surface none, 3 source files). A code review ran anyway, by the agent's choice, because the diff narrowed two safety barriers: the lane folder wipe that kept hidden tests out of lanes, and (until it was dropped) the force-push backstop. It ran as the built-in `code-review high --max-findings all`, over 7 rounds; rounds 3–7 were each allowed by the user at the review cap.

**Verdicts.** r1 FAIL (F1 F2 F3 F7, all medium bugs) · r2 FAIL (6 highs: selective clean-up in `copy_to_lane` leaked hidden-test files; backstop split bypasses) · r3 FAIL (R3-1 high, backstop in heredocs; lane_plan clean of hidden-test paths) · r4 FAIL (R4-1 `$[…]`) · r5 FAIL (R5-1 quoted `${…}`) · r6 FAIL (R6-1 `function`/`$@`, R6-2 quote misalignment) · r7 FAIL (R7-1–3 `xargs` carriers) — waived: bash_guard.py reverted to Base, 4i dropped by the user. Reports: `.sdlc/.work/findings/2026-11-17-m-crm-lane-upgrade-fixes/code-reviewer-r1.md` … `-r7.md`.

**High findings and what fixed them.**
- r2 4f leaks (R2-3, R2-4, R2-9, R2-13): `copy_to_lane` redesigned to wipe and rebuild `acceptance/` from every open test up to the lane's slice; an open test sharing a hidden test's file is refused; the lock's hidden path is read in either slash and with a leading `./`.
- r2–r7 backstop bypasses: 4i dropped (see Why).
- Mediums fixed on the way: F1/F2/F7 (stale own copies, manifest entries, seed) by the redesign; R3-8 Drop criteria carried into lanes; stale comments in upgrade.py and lane_plan.py.

**Tickets** (to #16): earlier-slice integrity checks now refuse every later lane (R3-9); lane lock blanks `test` by manifest visibility, not the split record (R3-12, pre-existing); duplicate `/` and `\` manifest keys keep the later JSON entry, which fails safe (F6/R4-9); build `rel` with `/` at the source (F5); `_norm` and slices-up-to derivation duplicated (R3-15, R3-16); 4i in the tokenizer: `verdict()` blind to heredoc bodies, `$[…]`, embedded computed words and `xargs` stdin (R3-2, R4-2, R6-3, R7-4).

**Drift.** Deviations in the state file: the eval helpers of `upgrade_manifest_keys.py`; the 4i criterion added then removed with 4i; `copy_to_lane` gains `slice_id`; each test change re-run red at Base 7558bde.

**Manual checks.** None. **Tests.** Suite fails only on the 4 baseline lines (`.sdlc/baseline.md`); AC-001–005 red at Base, green now.
