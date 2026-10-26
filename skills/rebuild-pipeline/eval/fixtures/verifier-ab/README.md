# verifier-ab — does a verifier pay for itself?

The eval behind removing the per-lane verifier loop (1.1.0). It compares ways of checking one lane's
work against its approved `PLAN.md`:

| Arm | Setup |
|---|---|
| A | one agent implements, then audits its own work in the same context |
| B | an implementer, then a fresh read-only `lane-verifier`; a `FAIL` resumes the implementer (cap 3) |
| C | an implementer alone |
| D | an implementer, then `tools/check_plan.py` (every row Done with a named test, every rule id in a test, own suite green); a failure resumes the implementer |

Each task is a spec with acceptance criteria and rule ids, a reference solution, and **hidden tests**
(one group per criterion) that no agent can read. The score is the number of criteria whose tests all pass.
`tools/validate_fixtures.py` proves the tests are worth trusting: the reference passes every criterion, and
every criterion has a mutant (one plausible wrong reading) that fails it.

## Run it

```sh
python3 tools/validate_fixtures.py                       # fixtures are sound
python3 tools/prepare.py <task> <run-dir>                # a git repo with PLAN.md and tests/
python3 tools/briefs.py worker <task> <arm> <run-dir> <brief.md>
# dispatch an implementer agent told to read <brief.md>; for B, dispatch a fresh verifier built with
#   briefs.py verifier <task> <run-dir> <base-sha> "<its test line>" <brief.md>
python3 tools/score.py <task> <run-dir>                  # per-criterion JSON
```

Tasks: `invoice`, `ratelimit`, `subscription` (6 criteria each), `shipping`, `coupons`, `leave` (11 each),
and `bundle` (all three of the last, 33 criteria in one lane). The worker and verifier rules are pinned
copies (`tools/worker_rules.md`, `tools/verifier_rules.md`): the first pilot read the live
`agents/lane-worker.md` and an edit to it leaked a self-check line into every arm.

## Result (2026-10-26, Sonnet implementers and verifiers)

- Pilot, arms A–D on the first three tasks: every arm passed 18/18 criteria. Mean tokens per run: A 45.8K,
  B 88.9K, C 45.9K, D 46.1K. B's verifier returned `PASS` on all three lanes, so no fix round ran. Blind
  quality scores (1–5) were 4.25, 4.42, 4.08 and 3.92, a spread smaller than the spread between tasks.
- Calibration, arm C alone on `shipping`, `coupons`, `leave` and `bundle`: 33/33 criteria and 84/84 tests.
  A plain implementer does not miss rules in a precise spec, so the full matrix was not run.

## What it does not show

- A cheaper implementer (Haiku) may miss criteria a verifier would catch. Not run. If the build lane is
  routed to a cheap tier, rerun the `bundle` with that model across the four arms.
- Specs here are exact. A spec that drifted from what the legacy product does is invisible to a verifier
  that only reads `PLAN.md`, so this eval says nothing about it.
- Timings from runs dispatched in parallel share API load; use the agent-reported durations and tokens.
