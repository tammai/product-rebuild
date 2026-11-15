# product-rebuild 3.2.0: G5 cost optimization (bug-hunter tiers, target health guard, narrower step 0)

## Why

**Request (verbatim):** product-rebuild 3.2.0 G5 cost optimization (requested by the CRM rebuild, measured costs in C:\Users\Admin\orca\projects\crm-rebuild-sdlc\progress\costs.json). User decisions already made: (C) bug-hunter budget by per-slice risk tier in product-rebuild's own config — high = 6 hunters / 1.2M fresh (today's values), low = 2 / 400k, a slice with no tier gets high; (G) handoff sets rspec verify scope to MVP by default, Later verified at the step 0 of the slice that builds it, 'full' opt-in. Also: (D) step 0 re-verifies only the slice's own features' criteria without a level-2 test; (E) reference health preflight before batches of runs and abort on the first connection refused in boundary.py and holdout.py run (a refused run is 'not run', not 'fail'); (A) orchestrator guidance: fresh session per slice, slice boundary in a fresh agent, briefs point at files instead of pasting. Leave holdout.py:534's withheld detail as is (posture guard). Existing 3.1.0 workbenches must keep working without the tier field. Minimal tests: one per behaviour.

The CRM rebuild measured 763M tokens (24M fresh) before G5 started, 71% of it in rspec verify. G5 has 184 slices still to build. At today's 6 hunters / 1.2M per slice, bug-hunter alone could spend about 220M fresh tokens, about 9x everything spent so far. This change cuts the G5 costs that product-rebuild controls. The rspec side (full failing output, connection-refused handling in verify_run.py, the flaky rule, MVP verify scope, recording by criterion) ships separately as rspec 0.13.0.

**The user's words:** two risk tiers (recommended); a slice with no tier gets the high tier; MVP by default for verify; upgrade sdlc first (done, 3.6.1). The CRM's four borderline slices (6, 70, 150, 164) go high. That is the CRM workbench's own tagging, not this repo's.

## Decisions

| Decision | Ruled out | Why |
|---|---|---|
| Name the **low** slices (`low_tier_slices` in `rebuild.yaml` budgets); any slice not named is high | Naming the high slices | A missing tag then gives the old, larger budget, never a silent cut, as the user asked |
| The low budget lives beside the high one in `budgets:` (`hunters_per_slice_low`, `bughunter_tokens_per_slice_low`) | A tier field in rspec's build-plan | build-plan.md is rspec's format, and Gate 2 locks it; changing it would be a cross-plugin contract change |
| A workbench that lists low slices but has no low budget keys gets the high budget for them, with a note | A built-in 2 / 400k default | Avoids a budget nobody wrote in `rebuild.yaml` (05 P9: budgets are shown once and edited there) |
| Unreachable means the request failed with "refused" (or the preflight's request did): `not run`, then stop | A retry loop | The Docker outage of 2026-11-13 logged 181 false fails. Stopping costs one rerun; a retry hides a dead build |
| Step 0 names the missing **criteria** in its `rspec:verify --only` line | Feature IDs, as today | rspec 0.13.0 accepts criterion IDs in `--only` and records only those, so a slice with one missing criterion no longer re-records the whole feature. The dependency moves to rspec >=0.13.0 |
| A (fresh sessions, short agents) and G (verify scope MVP) are orchestrator text in SKILL.md, g5-build.md and subagent-briefs.md | A script | They are instructions for the orchestrating agent; nothing a script runs decides them |

**Proposals not asked for:** None.

## Acceptance criteria

- **AC-001** Given `rebuild.yaml` lists S1 in `low_tier_slices` with `hunters_per_slice_low: 2` and `bughunter_tokens_per_slice_low: 400000`, when `boundary.py S1` reaches step 5, then the bug-hunter command carries `--max 2 --budget 400000`.
- **AC-002** Given a 3.1.0 `rebuild.yaml` (no tier keys), when `boundary.py S1` reaches step 5, then the command carries today's `--max 6 --budget 1200000`. A freshly scaffolded `rebuild.yaml` holds the low keys and an empty `low_tier_slices`.
- **AC-003** Given `ACCEPT_BASE_URL` points at a port nothing listens on, when `boundary.py S1` runs, then it stops before the open suite with `not run` naming the address, writes no finding, and exits 2.
- **AC-004** Given the target stops answering, when `holdout.py run S1` runs, then the first refused criterion is `not run` (not `fail`), each later criterion is `not run` without a request, and no finding is written from the report.
- **AC-005** Given a slice where only some criteria of a feature lack a level 2 test, when `lane_plan.py step0` runs, then its `rspec:verify --only` line names those criterion IDs, not the feature.

## Acceptance tests

| AC | Test | Run |
|---|---|---|
| AC-001 | skills/rebuild-pipeline/eval/gp_eval.py › tiers | `python3 skills/rebuild-pipeline/eval/gp_eval.py tiers` |
| AC-002 | skills/rebuild-pipeline/eval/gp_eval.py › tiers | `python3 skills/rebuild-pipeline/eval/gp_eval.py tiers` |
| AC-003 | skills/rebuild-pipeline/eval/g6_eval.py › health | `python3 skills/rebuild-pipeline/eval/g6_eval.py health` |
| AC-004 | skills/rebuild-pipeline/eval/g6_eval.py › health | `python3 skills/rebuild-pipeline/eval/g6_eval.py health` |
| AC-005 | skills/rebuild-pipeline/eval/lanes_rspec.py › step0 | `python3 skills/rebuild-pipeline/eval/lanes_rspec.py step0` |

## Must never break

- holdout.py's withheld detail for a failing hidden test (holdout.py:534): a refused request says only "connection refused", never the test's text.
- A slice without a tier, or a workbench without the new keys, never gets less checking than 3.1.0 gave.
- `boundary.py` still refuses the reference's address as the target (reference_target) before any health check.

## Failure modes

- Persisted data from older versions: a 3.1.0 `rebuild.yaml` without the new keys → AC-002.
- I/O error mid-run (the target dies) → AC-004, and the open suite stops the same way through the shared check.

## Out of scope

- rspec's verify changes (full failing output, the flaky rule, verify scope, connection refused in verify_run.py, recorder per feature): rspec 0.13.0, its own change.
- Tagging the CRM's slices: done in the CRM workbench, by its session.
- Hard caps on agent steps: Claude Code agent definitions give no turn cap these briefs could rely on, so the cap is guidance in the brief.

## Review

- **Recommended and chosen:** code, because `## Public Surface` adds three `rebuild.yaml` budget keys; chosen by the trigger list (low risk, not asked).
- **Verdicts:** code-reviewer (built-in `code-review high --max-findings all`) → `.sdlc/.work/findings/2026-11-15-m-g5-cost-tiers/code-reviewer-r1.md` → FAIL — CR-1..CR-10; closing check → `code-reviewer-r2.md` → PASS (no high; medium bugs fixed in the same round, test first).
- **Fixed:**
  - Round 1, high:
    - **CR-1:** the boundary went on to equivalence and bug-hunter after the build died in the open suite. It now stops after the open suite, the hidden suite and before equivalence (R2-2).
    - **CR-2 and CR-4:** only a refused run-http counted as "down". After any failed HTTP or Playwright run the build is now asked again, so refused, reset, closed and timed out all count.
    - **CR-3:** a `break` dropped later JUnit results. Now only later HTTP tests are skipped.
  - Round 1, medium:
    - **CR-5:** the skip now applies only to runners that use the build URL, after the manifest check.
    - **CR-6:** the health check runs after the exposure and reconcile checks.
    - **CR-7 and CR-8:** block lists and `S01` are read, and an unreadable list or a non-positive low budget gives the high budget with a reason.
    - **CR-9:** an eval of a build that answers `/` and dies on its first test.
    - **CR-10:** the step 0 assertion is pinned.
  - Round 2, medium:
    - **R2-1:** the test the build died at is named.
    - **R2-3:** a gateway's 502, 503 or 504 means down.
    - **R2-4:** the probe allows 30 s, run-http's own request timeout.
    - **R2-5:** integrity checks run before an outage skip.
    - **R2-6:** the outage is the report's own `down` field.
    - **R2-9:** a comment inside the block list no longer cuts it short.
    - **R2-10:** quoted and non-ASCII digits in the low budget are handled.
  - Tests: `g6_eval.py health` (5 checks) and `gp_eval.py tiers` (7 checks) prove them.
- **Tickets:**
  - **R2-7:** evals for CR-3 (JUnit after an outage), CR-5 (maestro, missing entry), CR-6 (exposure over a dead target) and CR-2's Playwright path.
  - **R2-8 and CR-11:** one shared health probe instead of `holdout.answers` and `preflight._probe`, with a structured transport-error signal from contracts' run-http.
  - **R2-12 and CR-12:** the boundary's probe and `holdout.py run`'s probe repeat each other.
  - **CR-13:** fixed in passing as R2-11.
- **Drift and manual checks:**
  - **Deviations:**
    - The first red step recorded a SyntaxError, so red was proven by hand against the old scripts.
    - `docs/PLAYBOOK.md`'s step 0 line.
    - `holdout.answers` and the former `unreachable` became internal functions.
    - A comment in `route.py`.
    - `holdout.integrity`.
  - **Test step:** the four failures listed in `.sdlc/baseline.md` (lane_guards worktree count, run_supervision ×2, windows_and_upgrade CRLF) still fail, and no other check fails.
- **Lessons filed:** `docs/sdlc/recurring-defects.md` (a health check that recognises one spelling of "down").
