# Subagent briefing format

Since 3.0.0 this pipeline dispatches one agent of its own, the build lane (`lane-worker`). The spec side is
rspec's: its stages run their own agents (module explorers, story writers, tech analysts, auditors, recorders)
from their own briefs, and nothing here re-briefs them. A lane's reviews are sdlc's agents, briefed the way
sdlc's Review says (G5 step 4b). bug-hunter's hunters are briefed by bug-hunter.

Every dispatch is self-contained — subagents share no conversational context. Include:

1. **Role file**: `agents/lane-worker.md`.
2. **Inputs** (absolute paths): the lane's worktree, its sdlc change and state files, and the sdlc folder
   `lane_plan.py` printed. Never the holdout or the reference checkout under posture `strict` or `observe`: the
   reference guard denies them, and a brief that names them only invites the call.
3. **Output contract**: the lane's sdlc feature at the end of Build (`verify.py` passing).
4. **Boundaries**: what the agent must NOT do — no edits outside its worktree, no criterion edits (a wrong one is
   a spec question, sdlc's `state.py question`), no restructuring locked artifacts.
5. **Done means**: a checkable condition (`verify.py` passes in the worktree; every AC red then green).
6. **Model + tier**: the `model` and `tier` `scripts/routing.py --role build-lane` resolved, stated in the brief as
   well as passed on the Agent call. On the record it is checkable after the fact; passed only as a parameter it is
   not.

## Context budget (carried by the agent file; do not paste it)

One audit day cost ~200M tokens, ~85M of it a single drafter that read the parent session's transcript. Every
subagent turn re-bills the whole context so far. The three rules that prevent it (never read session transcripts
or scratchpad dumps, keep every tool result under ~20K characters, read each file once) are in `lane-worker`'s
agent file. Add them to a brief only for an agent that is not `lane-worker` (a helper a lane spawns, or a fork),
since nothing else delivers them.

## Keep agents short (measured on the CRM rebuild, 2026-11)

Cache reads, not fresh tokens, made up most of the bill: one long-lived agent ran 247 steps at about 250k context per
step. So:
- One agent per unit of work small enough to finish in a few dozen steps: a lane, a feature, one disputed
  criterion. Never one agent per module.
- A brief points at files by path and says which part to read. It never pastes a file, a log or an earlier
  agent's report.
- Two failed attempts at the same thing go to a fresh agent that gets only the artifacts (the test, the failure
  output), never to a third attempt in the same context.
- Claude Code gives these agents no turn cap a brief can rely on. Put the step budget in the brief ("stop and
  report after about 40 steps").

## The reference adapter (after Gate 3, before verify)

Only when `sources.yaml` says `reference.adapter: required`. It's an sdlc feature in the workbench (`/sdlc:start`, files under `adapter/`), built against `docs/openapi.json` as rspec:tech wrote it (Gate 4 locks it with the tests). The brief names, as paths: the contract, `docs/domain.md`, the reference's API docs (`sources.docs`), the plugin's `docs/specs/contract-shaped-tests/design.md`, and these rules:

- **A pass-through.** Each contract operation the MVP criteria use maps to calls on the running reference, at the URL in the variable `rspec.json` `reference.run.base_url_env` names (the adapter is started with the user's environment). Every response comes from those calls in that request. It keeps no state, cache or stub of its own.
- **When it can't map an operation,** it answers 501, and the criterion is `unrecordable "adapter: …"` until the mapping is added.
- **When the reference doesn't answer,** it returns 502, so rspec's `verify_run.py` stops as `not run` instead of logging failures.
- **The request log**, `parity/adapter/requests.jsonl`. It stays git-ignored (`parity/adapter/` in `.gitignore`; an older workbench adds the line itself, and Gate 4 names it until it does): it names every recorded request, the hidden tests' too, and Gate 4 refuses a committed one. Each time the adapter starts, it appends `{"start": "<ISO 8601 with a timezone, e.g. …Z>"}`, then one JSON line per request served: `method`, `path`, `status`, `reference_calls` (how many calls it made to the reference). No bodies, headers or tokens. `python3 scripts/adapter.py audit` checks every run started since the adapter's last commit (each restart during verify is a run): it fails on any response other than 501-504 with `reference_calls: 0`. Gate 4 refuses until that audit passes, and while any open (not hidden) MVP level-2 HTTP criterion has no passing run since that commit (after an adapter fix, re-record what it touches). It records the result in its lock.
- **Its own tests** run against the live reference, one per operation. Its own URL goes in the variable `rspec.json` `reference.run.adapter.base_url_env` names (e.g. `ACCEPT_ADAPTER_URL`, never `ACCEPT_BASE_URL`).

Commit and merge the adapter before verify. Any later commit under `adapter/` (even a README, an amend or a squash-merge) means re-recording every open HTTP criterion. Hidden criteria aren't re-checked, because their tests can't be re-recorded after the split, so don't change the adapter between the split and the first Gate 4 lock. Gate 4 hashes the files git tracks under `adapter/` (keep build output git-ignored there). A fix after the lock (a judge's `adapter:` verdict at a later step 0) needs a Gate 4 reopen, then a re-verify of the criteria it touches.

## The build-lane brief (G5)

`lane-worker`'s agent file carries the standing rules, so they are not pasted into each brief (a rule that lives
in every brief drifts between them): the **test cadence** (what to run while building, at the joint run, and on
the rerun of failures), the **long-run rules** (`run_in_background`, `run_phases.py`, what counts as green), the
**migration** rules and the **helper** rules. The cadence is also stated for the orchestrator in `g5-build.md`,
"Test cadence within a slice". `eval/lane_plan.py worker` checks the agent file still carries each rule. The brief
says only what is true of this dispatch:

- **Joint run:** none. The orchestrator stamps and starts the joint run and its rerun from the workbench root
  (lanes may not write the workbench); a brief at most names the suite commands the lane should report.
- **Migrations:** this lane's migration number (or range) for the slice, `<N>`, if its criteria change the schema.
- **Helpers:** whether this lane may run helper agents. The orchestrator opens each helper's lane with
  `lane_plan.py` when the lane asks, because that writes the workbench's lane records.
- **The record:** you work in `<worktree>` on branch `slice/<Sn>-<lane>`. Your lane is the sdlc feature
  `<feature>`: change file `<worktree>/<change>`, state file `<worktree>/<state>`. sdlc is installed at `<sdlc>`
  (`lane_plan.py` printed all four). Its ACs cite rspec's criteria, whose text is in the lock copy
  (`.rebuild/criteria.lock.json`) and whose recorded tests are in `acceptance/`. Your standing rules for it, and
  for the guards that run on this repo, are in your agent file.

Parallelism: dispatch independent lanes in the same turn, up to `rebuild.yaml` `budgets.parallel_lanes`. On a
lane's output failing `verify.py`, send it back with the error — do not hand-fix; the fix must come from a run
that could have produced it.

**Dispatch** (part 6): a build lane runs as the `build-lane` role, on the agent *and* model
`scripts/routing.py --role build-lane` resolves, passed as `subagent_type` and `model` on the Agent call. It is
`lane-worker`, never `general-purpose`: the standing rules live in the agent file, and a hand-written stand-in
prompt silently drops them.

## A lane's review (sdlc's, run by the orchestrator — G5 step 4b)

There is no review brief of this pipeline's own. sdlc's Review section (`flow.md`, its `## Review` section) says
what each review is told, and its `review-brief.md` is the brief: pass the paths it names (the lane's change file,
state file, `git diff <Base> -- . ':!.sdlc'` from the lane's worktree, the criterion ids, the report path under
`.sdlc/.work/findings/<feature>/`). Dispatch `sdlc:code-reviewer` and `sdlc:ui-reviewer` with the `subagent_type`
and `model` that `scripts/routing.py --role lane-review` and `--role lane-ui-review` resolve (opus; sdlc's router
denies a review below it). An M lane's code review is the built-in `code-review` skill, which picks its own model.

Add one line of pipeline context: "The criteria are rspec's, locked in a rebuild workbench at Gate 4 (the lock copy
is `.rebuild/criteria.lock.json`); a criterion's `then` is what the build must match."

## Which model each role runs on

`scripts/routing.py` maps each role to a tier once, resolves the tier through the project's
`.claude/model-routing.json` ladder, and prints the `model` to pass. Run it once per session (SKILL.md step 4b has
the command) and read the values off it; do not re-derive a tier from the shape of the task. The tiers it assigns,
and the argument for each, are in the script's `ROLE_TIERS`.
