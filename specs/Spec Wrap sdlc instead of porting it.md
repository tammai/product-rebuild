# Spec: product-rebuild wraps sdlc

2026-11-02 · @Tam Mai · draft for sign-off

## Problem

Since 1.0.0 this plugin carries its own copies of what `tammai/sdlc` (2.2.0) already does better: scaffolding a repo, a build-lane agent, a verifier, commit and bash guards, a spec gate, an interpreter probe. NOTICE.md lists each one as "adapted from sdlc". Every sdlc fix has to be ported by hand, or the copies drift. The 2026-10-26 spec chose that deliberately ("Port into this repo with attribution. No runtime dependency on `sdlc`"). **This spec reverses that decision.**

## Decisions (interview, 2026-11-02)

| Question | Decision |
|---|---|
| Scope | `sdlc` **and** `sdlc-extras`. |
| Shape | **product-rebuild is a wrapper around sdlc.** Where the two overlap, sdlc owns it. Nothing is copied or duplicated from sdlc into this repo, and what we already copied is deleted. |
| Integration | **G5 is wired into sdlc now**, not as a follow-up. |
| Hosts | sdlc keeps its Codex, Cursor and Antigravity adapters. This plugin carries none and is Claude Code only, because the other hosts do not resolve Claude Code dependencies. **Confirmed.** |
| Existing rebuilds | **Breaking change, no migration.** 2.0.0 does not operate on a workbench or code repo built on 1.x, and there is no compat code. |
| Marketplace | product-rebuild is published in **the `sdlc` marketplace**, next to `sdlc` and `sdlc-extras`, so all three resolve within one marketplace. |

## Mechanism

Claude Code resolves plugin dependencies natively (`plugin.json` → `dependencies`).

```json
"dependencies": [
  { "name": "sdlc",        "marketplace": "sdlc", "version": "^2.4" },
  { "name": "sdlc-extras", "marketplace": "sdlc", "version": "^2.4" }
]
```

- **`^2.4` is the floor because 2.4 carries the fix this plugin needs** (hookify and `role_guard` work in a session started above the repo; spike finding 2, option A below). Released as `sdlc--v2.4.1` on 2026-11-02; there is no 2.4.0 tag, which a range does not need.
- **The marketplace move, in order.** product-rebuild ends up in the `sdlc` marketplace, installed as `product-rebuild@sdlc`. That needs a `product-rebuild` entry (source `github`, `tammai/product-rebuild`) in `tammai/sdlc`'s `.claude-plugin/marketplace.json`, which is a change in that repo. Until the entry exists, existing installs update through this repo's own `product-rebuild` marketplace, so:
  - **1.6.0** keeps this repo's `marketplace.json` and adds `"allowCrossMarketplaceDependenciesOn": ["sdlc"]` to it. Without that line the install completes **without** sdlc and the plugin then fails to load. The dependencies name `"marketplace": "sdlc"` explicitly, so they resolve the same before and after the move.
  - **The `sdlc` marketplace entry** is added once 1.6.0 is on `main`, so the first `product-rebuild@sdlc` install already has the dependencies.
  - **2.0.0** deletes this repo's `marketplace.json`. Two marketplaces cannot share the name `sdlc`, and keeping a second one alive would split installs. An install of `product-rebuild@product-rebuild` stops updating then and is reinstalled as `product-rebuild@sdlc`, as the breaking release says.
- **Version ranges resolve.** sdlc is tagged (`sdlc--v1.8.0` … `sdlc--v2.4.1`). `sdlc-extras` has no tags of its own; it is a relative-path entry, so a missing tag does not fail the install. Claude Code uses the marketplace's current copy and checks the range against its `plugin.json`, which says 2.4.1. This holds while extras is versioned with sdlc, as it has been.
- **No preflight check.** Claude Code disables a plugin whose dependency is missing, disabled or out of range, so a rebuild cannot reach `preflight.py` without sdlc. A script check would only repeat what the loader already refuses.
- Skills and agents keep sdlc's namespace: this plugin calls `sdlc:orchestrator`, `sdlc:setting-up-projects`, `sdlc:code-reviewer` and so on. No rename, no aliases.
- **What 1.6.0 changes at runtime.** sdlc's hooks now load in every rebuild session. A 1.x workbench and its code repos have no `.sdlc/`, so they stay silent: `model_router`, the session status line and the stop hooks act only on an active sdlc feature, and hookify looks below the session only into a folder with `.sdlc/config.json`. `role_guard` still holds sdlc's own agents to their role wherever they run; 1.x never dispatches one. Checked against the installed 2.4.1 with a workbench parent over a repo without `.sdlc/`.

## Overlap map

| Here today | sdlc owner | Becomes |
|---|---|---|
| `skills/scaffold-repo/` (10 files) | `sdlc:setting-up-projects`, `scripts/scaffold.py` | **Shrinks to a generate step** (spike finding 1): the playbook manifest's generator, `after` and seed files stay here, then sdlc setup runs on the result by its brownfield path. The interview, commands, rules, guardrails, CI and pointer rendering go. |
| `agents/lane-worker.md` | sdlc Build phase, `sdlc:test-driven-development` | Deleted. What is specific to a rebuild lane (migration numbers, the test cadence, `run_phases.py` long runs, the `amending` stop) moves into the lane brief and a seeded `.claude/rules/` file in the code repo. |
| `agents/lane-verifier.md` | `scripts/verify.py`, `sdlc:code-reviewer`, `sdlc:qa-tester` | Deleted. The user-requested audit at step 4b becomes an sdlc review. |
| `hooks/scripts/bash_guard.py`, `commit_gates.py`, `commit_rules.py` | sdlc `pretooluse.py` guardrails, hookify rules | Deleted in phase 3, after phase 2 shows sdlc's guardrails catch the same calls from a workbench session (sdlc 2.4 made them reach the repo; spike finding 2). |
| `hooks/scripts/spec_gate_guard.py` + `lane_plan.py` | sdlc state and change files, `verify.py` plan drift | Replaced. `lane_plan.py` writes the lane's sdlc change and state files from the approved spec instead of `PLAN.md`. |
| `hooks/py.sh` | `hooks/sg-python.sh` | Deleted. |
| `routing.py` model ladder | sdlc `model_router.py` (PreToolUse on Agent) | Compatible with a rule (spike finding 3): `model_router` denies, never overrides. `routing.py` must keep `haiku` and sonnet-reviewers off sdlc agents. |
| `autopilot.py` | sdlc `--autopilot`, `scripts/autopilot.py` | **Nesting.** Rebuild autopilot is the outer loop and halts at gates. sdlc's never asks. The lane brief must say which applies. |

**Stays, because sdlc has nothing like it:** every gate, the workbench and its locks (`gate_guard`, `flows_guard`, `autopilot_guard`, `runbook_guard`), mining, the feature matrix, slicing, ADRs and contracts, the injection scan, gate and canary, parity and the joint run, `slice_review.py`, `boundary.py`, the playbooks and the vendored PyYAML.

## G5 after the change (phase 2 design, draft 2026-11-03)

**One lane is one sdlc feature in its worktree, entered at Build.** You approve a slice's specs exactly as today. At that moment `lane_plan.py` writes the lane's sdlc record instead of `PLAN.md`: the change file (`## Why` points to the approved spec paths; one `AC-nnn` per spec criterion, each keeping its `rule_id` and test level) and the state file via sdlc's own `state.py new`, advanced to Build with the approval in its Gate log (approver, spec paths, workbench commit). The lane starts at sdlc's Build: it writes each criterion's test, records it red with `verify.py red`, writes the code, then runs `verify.py` once. The record is sdlc's from then on: `git blame` leads from a line to the change file, and the change file to the rebuild spec.

Found while preparing the phase 2 lane spike (2026-11-03):
- **sdlc feature names are lowercase** (`state.py new` refuses `S1`). A lane's feature is `<date>-<track>-s<n>-<lane>`, e.g. `2026-11-03-m-s1-pricing`; the git branch keeps `slice/S1-<lane>`.
- **`lane_plan.py` must not rewrite history after `state.py new`.** The state records `Base:` as the HEAD at that moment; the spike amended the record commit and left `Base` pointing at a commit that no longer existed (fixed with `state.py set <f> Base`).
- **A feature that `lane_plan.py` advanced to Build is already at Stage 4**, and `state.py advance <f> 4` on it is refused. sdlc's Build step 1 runs `$S advance <f> 4 … && $V red …`, so the lane brief says to run only the `$V red` half.
- **The acceptance tests table is the lane's to fill.** The spec names each criterion's level, not its test, so `lane_plan.py` writes the Test and Run cells as `TBD` and the lane fills only those cells.

**Lane spike result (2026-11-03): a lane runs as an sdlc feature.** One `general-purpose` subagent on sonnet, dispatched from a session whose project directory has no `.sdlc/`, built a two-criterion lane in a worktree below it from the record `lane_plan.py` would write. It wrote the tests, `verify.py red AC-001 AC-002` recorded both red, it wrote the code, and `verify.py` passed (the fast suite, each criterion's own test, the drift check). It made one Conventional commit naming the change file: 13 tool calls, about a minute. It edited only the Test and Run cells of the change file. sdlc's force-push guardrail blocked its force push to main, which is the 2.4 fix reaching a lane. What it found:
- **The Test cell is a test file path**, not `file::test`; `verify.py red` reports anything else as not found. The test id goes in the Run cell.
- **`## Public Surface` must be written by `lane_plan.py`.** The approved spec names the module's public names; left as `- none`, every new export is drift, and the lane logs deviations for names the spec itself asked for.
- **Red needs the names to exist.** The lane wrote a stub raising `NotImplementedError` so its tests failed rather than errored; the brief says so.
- **Type the sdlc script paths in full**, as sdlc's own flow says: zsh does not word-split `$S`.
- **sdlc's guardrails judge command text in any session whose shell sits inside a set-up repo,** including the orchestrator's own: a spec edit quoting the force-push command was blocked while the shell's directory was the lane worktree. The orchestrator writes documents with its file tools, as sdlc's flow already says.

Fixed by constraints, not choices:
- **The orchestrator runs sdlc's Review, not the lane.** A lane cannot ask the user, and sdlc's Review stops for the user (the choice on high risk, a failed round 2, a disputed high finding). The spike showed the Agent tool *is* listed for a lane subagent, so this rests on the stops, not on a missing tool.
- **The approval is written by script, never by the lane** (unchanged reasoning from `lane_plan.py`). Calling sdlc's `state.py` needs sdlc's install path: `lane_plan.py` takes it from `installed_plugins.json`, overridable with `--sdlc-root`.
- **The spec gate stays, repointed.** sdlc has no "no code before an approved plan" block, so `spec_gate_guard.py` keeps that job, reading the sdlc state file (`Status: active`, past Define, the approval line in the Gate log) instead of `PLAN.md`. sdlc's trust anchor also reports an edit to the change file's criteria, which joins `slice_review.py`'s hash check.
- **`lane-worker` stays, slimmed.** It keeps only what sdlc has no word for: migration numbers, long runs and `run_phases.py`, the joint run and rerun, `cd <worktree> &&`. The build loop itself is sdlc's (`flow.md`, Build). `lane-verifier` goes.

Decided 2026-11-03, all three as recommended:

**D1. Test cadence: the fast suite.** `verify.py` runs the repo's whole verify plan (lint, typecheck, build, `commands.test`) every time, which rebuild forbids per lane. Chosen: **define `commands.test` as the fast suite** (unit and fixture tests) in each code repo's `.sdlc/config.json`; integration, E2E and the deploy suites live outside sdlc's commands and run only at the joint run, which stays rebuild's. Each criterion's own test still runs alone through its `Run` command. No sdlc change. Alternative: ask sdlc for a scoped `verify.py` (an upstream change).

**D2. Reviews: sdlc's table, per lane.** sdlc's table fires a code review on any diff over 5 files or 300 lines, so nearly every lane would get an opus review; 1.1.0 removed per-lane verification for cost. Chosen: **the orchestrator runs sdlc's Review per lane, after the lane reports, using sdlc's table unchanged** (security on high risk, code on large diffs, UI on UI paths), because review is overlap and sdlc owns it. Alternative: lanes stop at Build and review stays the user's call at the slice boundary, as today.

**D3. Repo setup: prefilled from the workbench.** sdlc setup stops for the PRD, constitution, design system, plugin keys, CI and the merge. Chosen: **the scaffold answers what the workbench already decided** (PRD: a pointer to the workbench's product docs; constitution: from the Gate 3 ADRs; plugin keys: the team file; CI: sdlc's, with rebuild's license and AC-coverage jobs added) and asks only what is left, in one batch.

## What it costs

- **Breaking:** `lane-worker`, `lane-verifier` and `scaffold-repo` disappear, and `PLAN.md` stops being the lane contract. Ships as **2.0.0**.
- Every code repo gets sdlc's `.sdlc/` scaffold and its hooks. A rebuild in flight on 1.x has `PLAN.md` lanes and is not carried over: no migration, no detection, no compat code.
- sdlc's hooks (`UserPromptSubmit`, `Stop`, `PreToolUse` on Agent, Read, Grep, Glob) now run in rebuild sessions too.

## Spike findings (2026-11-02, against sdlc 2.3.1)

Read from the 2.3.1 tag and run: the real hooks, fed hook-shaped input, against a scratch workbench (a parent directory holding a code repo with an active feature, a `.sdlc/config.json` and sdlc's 15 hookify guardrails installed). Each hook ran twice: with `CLAUDE_PROJECT_DIR` at the workbench parent, which is where a rebuild session starts, and at the code repo. Not yet tried: a real `/sdlc:start` lane in a live session.

**Root cause, behind findings 2 and 3.** sdlc finds its state and its rules from `CLAUDE_PROJECT_DIR`, i.e. it assumes the session's project is the repo. A rebuild session starts in the workbench's parent and works in several repos and worktrees. This is the same gap the 1.0.0 spec closed for the bash and spec guards.

1. **Scaffold manifest: sdlc cannot consume it.** sdlc's setup is a prose procedure (`setting-up-projects`) over a bookkeeping script, interview first, with no machine-readable input. The playbook's `scaffold.json` carries generator commands, `after` steps that add dependencies (gin, riverpod), and per-option seed files. sdlc's greenfield flow adds nothing beyond the generator unless the user opts in each item. **Consequence:** a thin generate step stays here (run the generator, the `after` steps and the seed files), then sdlc setup runs on the result by its brownfield path, which records the commands and renders rules, guardrails, CI and the PRD. What goes: the `plan` interview plus `commands`, `contract`, `run-commands` and the `render` steps of this plugin's `scaffold.py` (720 lines).
2. **Hooks are not neutral in a workbench session.** With the session at the workbench parent:
   - **Inert:** hookify guardrails: `git push --force origin main` returned `{}` (allowed) here and was denied with the session at the repo. Only that rule was run; the other 14 (reset-hard, dangerous-rm, secret values, …) load from the same `$CLAUDE_PROJECT_DIR/.claude/hookify/` directory; `model_router`; the session status line; `verify_freshness`, `stop`, `prove_budget`, `review_rounds`, `trust_anchor`. This is the "guards go silently inert" failure 1.0.0 was written to remove, so **`bash_guard.py`, `commit_gates.py` and `spec_gate_guard.py` cannot be deleted until this is fixed.**
   - **Harmful:** `role_guard` denied an `sdlc:code-reviewer` writing its report to `api/.sdlc/.work/findings/…`, because it compares the path with `.sdlc/…` from the project root. A review dispatched from the workbench cannot write its findings.
3. **Model routing does not override, it denies.** `model_router` never rewrites `model:`; `routing.py` always names one, so "name the model" is met. It acts only where a feature is active under `CLAUDE_PROJECT_DIR`, and there it denies: `haiku` (the `frontier` profile example routes the miner to haiku); `fable` unless the state says `Top model: fable`; and the review agents (`code-reviewer`, `feature-reviewer`, `ui-reviewer`, `qa-tester`, `pr-test-analyzer`, `silent-failure-hunter`) on anything below opus. Rebuild's `verifier` tier is `sonnet`, so an sdlc reviewer dispatched on that tier would be denied. Rebuild's own agents (`miner`, `rubric-judge`) are not in sdlc's list and pass.

## Decided: fix sdlc upstream (option A)

Findings 2 and 3 were one question: where does a lane's sdlc session run? The options were (A) fix sdlc so its hooks find the repo a call acts on, (B) one headless `claude -p` session per lane, (C) keep this plugin's own guards. **A was chosen (2026-11-02), on the condition that nothing changes for anyone running sdlc today.**

Shipped in sdlc 2.4 (`feat(hooks): hookify and role guard work in a session started above the repo`). Only `pretooluse.py` (hookify) and `role_guard.py` changed. In a session whose `CLAUDE_PROJECT_DIR` has no `.sdlc/` at all, a call into a folder strictly inside it that has `.sdlc/config.json` gets that repo's hookify rules (added to the session's; the repo's wins on a name clash) and `role_guard` judges the path against that repo. A session with any `.sdlc/` takes the old path unchanged. Verified here: the sdlc suite on the branch, 363 tests OK (the 2.3.1 baseline was 355, none edited); 7 identical outputs against 2.3.1 with the session at a repo; both spike repros fixed; and again on the installed 2.4.1.

Limits that bear on G5, from sdlc's notes:
- A Bash call is placed by its text: `git -C`, a leading `cd`/`pushd`, then its `cwd`. Lanes already start every command with `cd <worktree> &&`, which this needs. `bash -c "cd …"` and scripts are not placed.
- Paths are compared as text, so a workbench reached through a symlink (`/tmp` against `/private/tmp`) silently takes the old path. Workbenches live at real paths.
- Codex gets no fix: its hooks receive no project directory. This plugin is Claude Code only, so that does not bear on it.

Still open, for phase 2: `model_router` denies an sdlc reviewer below opus, `haiku` and an unrequested `fable` while an sdlc feature is active in the session's project. With the session at the workbench parent it is silent (it reads only `CLAUDE_PROJECT_DIR`), so a lane dispatched from the workbench is not checked by it at all. Whether that is acceptable, or `routing.py` should hold the same floor itself, is decided with the G5 swap.

## Phasing

0. **Spike.** Done: findings above, and option A shipped in sdlc 2.4. A lane then ran as an sdlc feature from a session above the repo (2026-11-03, result in "G5 after the change").
1. **Dependency.** `plugin.json` dependencies, the allowlist in this repo's `marketplace.json`, README install section. Ships as 1.6.0 and changes nothing else. Then the `product-rebuild` entry in the `sdlc` marketplace (a change in `tammai/sdlc`).
2. **G5 swap.** `g5-build.md`, `g5-first-slice.md`, `subagent-briefs.md`, `lane_plan.py`, `slice_review.py`, `parity.py`, `acsuite.py`, `routing.py`, and the autopilot nesting.
3. **Delete.** Superseded agents, skills, hooks and scripts; this repo's `marketplace.json`; NOTICE.md, licenses/ and CHANGELOG; release 2.0.0.

## Evals

Lane R (`agents/miner.md`, `schemas/rule.schema.json`) is untouched, so the rules-recall fixture does not apply. The existing preflight, validate and lane-plan checks stay green at each phase. Phase 2 adds one end-to-end check: a lane built through sdlc produces the same `parity/<date>-ac.xml` the joint run consumes today.
