# Subagent briefing format

Every dispatch is self-contained — subagents share no conversational context. Include:

1. **Role file**: point at the agent definition (`agents/<role>.md`: miner, adr-drafter, data-model-drafter, spec-writer, rubric-judge, lane-worker, lane-verifier).
2. **Inputs** (absolute paths): the exact workbench files to read. Never "the matrix" —
   always `workbench/matrix/features.yaml`. For miners: the `sources.yaml` entries in
   scope and the pinned reference commit. For lane-D miners specifically, also include the
   reference checkout's `graphify-out/graph.json` path when it exists (see
   `g1-mining.md`'s ground-truth graph step) so the miner queries it instead of grepping
   raw source cold. For adr-drafter (G4a): always include
   the workbench's **`adr/playbook.md`** as a fixed input alongside the per-ADR brief — the
   vendored copy, never the plugin's registry file — and the drafter's **excerpt** of it
   (`playbook.py excerpt <concern>`, g4a-architecture.md "Dispatch"), which is what it reads, plus the **concern key** and the exact
   **section(s)** the playbook's `concerns:` map gives for it (or `N/A` where it has no
   answer). Never leave the drafter to infer the section itself: numbering is per-playbook,
   so an inferred section is wrong in a way that reads as right. For the decomposition/stack
   ADR specifically, also pass along whatever the human said about team-composition facts
   bearing on the playbook's default versus its alternate. Pass `target_shape` too when it is
   `client-only` — it changes what the drafter may propose about the API (see the agent file).
3. **Output contract**: the exact output path and schema file. One output file per run.
4. **Boundaries**: what the agent must NOT do — no edits outside its output path, no
   fetching outside `sources.yaml`, no restructuring locked artifacts, no invented
   evidence. Ambiguity resolves by flagging `confidence: low`, never by guessing.
5. **Done means**: a checkable condition (validates against schema X; covers files Y).
6. **Model + tier**: the `model` and `tier` `scripts/routing.py` resolved for this role, stated
   in the brief as well as passed on the Agent call. On the record it is checkable after the
   fact; passed only as a parameter it is not, and a dispatch that silently ran on the wrong
   rung looks exactly like one that ran on the right one.

## Context budget (carried by the agent files; do not paste it)

One audit day cost ~200M tokens, ~85M of it a single drafter that read the parent session's
transcript. Every subagent turn re-bills the whole context so far, so one large read early in a
run is paid again on every later turn. The three rules that prevent it are in the agent file of
every role this pipeline dispatches (`miner`, `adr-drafter`, `data-model-drafter`, `spec-writer`,
`rubric-judge`, `lane-worker`, `lane-verifier`): never read session transcripts or scratchpad dumps, keep every
tool result under ~20K characters, read each file once. They used to be pasted into every brief as
well, about 275 output tokens per dispatch written out by the orchestrator for text the agent
already has. Dispatch each role by its agent (`subagent_type`), which is what carries them; a
brief does not repeat them.

Add the three rules to the brief only for an agent that is not one of those seven (a helper a lane
spawns, or a fork), since nothing else delivers them.

## The judge brief (`rubric-judge`, at every gate — Step 5.1b)

Same six parts, with these values. It runs once per gate attempt, after `validate.py`
passes, and it can run in the background while the gate review is drafted.

1. **Role file**: `${CLAUDE_PLUGIN_ROOT}/agents/rubric-judge.md`.
2. **Inputs**: the **gate id**; the **rubric** `${CLAUDE_PLUGIN_ROOT}/skills/rebuild-pipeline/references/rubrics/gate-N.md`;
   the absolute paths of the artifacts under that gate's `protects:`; and the supporting
   paths the rubric's own header says to read (findings, the NFR profile, the vendored
   `adr/playbook.md`, the latest parity report — they differ per gate, so take them from the
   rubric rather than from this list). For gate 4, say which mode G4b ran in — a
   `client-only` transcription is scored on two dimensions a `fullstack` draft is not.
3. **Output contract**: `plan/gate-reviews/gate-N-rubric.md`, in the format the role file
   specifies. Not schema-validated — it is a report for a human, not a pipeline artifact.
4. **Boundaries**: read-only over every input; no edits to the artifacts being scored (they
   are about to be hashed); no file written other than the output path; no recommendation to
   lock or not to lock. Uncertainty goes in the report's "What I could not check" section
   rather than being resolved by guessing.
5. **Done means**: every dimension the rubric defines has an integer score, and every score
   below 4 carries a file-plus-line or file-plus-id citation. Send a report back with the
   uncited dimensions named if it does not — same rule as a schema violation, and for the
   same reason: the fix has to come from a run that could have produced it.
6. **Model + tier**: the `model` and `tier` `scripts/routing.py --role rubric-judge` resolved, stated in the brief.

**Three files the judge should not have to build for itself**, all made by scripts before you dispatch
(each used to be the judge opening files one at a time, or you retyping them as model output):

- **Citation excerpts**, wherever the gate's artifacts carry `basis: transcribed` evidence (gate 1 on):
  `python3 scripts/cite_excerpts.py --out plan/gate-reviews/gate-N-citations.md`. The cited line and its
  neighbours next to each claim; an unopenable citation is marked, never skipped. Pass it as an input.
- **Computed facts**, for the two gates with arithmetic dimensions:
  `python3 scripts/gate_facts.py gate-1|gate-2 --out plan/gate-reviews/gate-N-facts.md` (ERD entities in both
  directions and feature counts per domain; feature counts per slice).
- **Evidence bundle** for gates whose artifacts are big (gate 3 ADR sets, gate 4 `openapi.yaml`, specs). You
  choose which ranges the rubric's dimensions touch; `python3 scripts/evidence_bundle.py --out
  plan/gate-reviews/gate-N-evidence.md path:start-end ...` copies them verbatim, each headed `path:start-end`.
  Never type an excerpt yourself: a retyped one is not verbatim, and one had quietly fixed a typo the judge was
  meant to score. The paragraph below applies to the bundle too. Pass the bundle as an input beside the artifact
  paths. The judge scores from it and opens the full file only for a targeted range when a dimension needs what
the excerpt left out — it is a starting point, not a limit on what the judge may check.
One run on 8 judge dispatches read `openapi.yaml` 25 times; the bundle is how that becomes 1.

One thing to get right when you dispatch it: **do not paste the gate review into the brief**.
The judge scores the artifacts, and a judge that has read your summary of them will grade the
summary.

Its rung is no longer a judgement call in this file — `routing.py` maps it to the worker tier
and the agent file pins `effort: high`, on the reasoning that scoring a whole artifact set is
omission-hunting and omissions are what effort buys. What used to be written here as "route it
to a high tier" is now the resolved value you pass.

## The data-model-drafter brief (`data-model-drafter`, G4b, one per bounded context)

Same six parts, with these values. Dispatch every context in one turn, as the `data-model-drafter` role on the
agent and model `scripts/routing.py --role data-model-drafter` resolves (`subagent_type` and `model` on the Agent
call; its agent file carries the rules and the context budget).

1. **Role file**: `${CLAUDE_PLUGIN_ROOT}/agents/data-model-drafter.md`.
2. **Inputs**: the context's name and its matrix features (ids); `findings/ground-truth/reference-erd.mermaid`; the
   Gate 3 ADRs that bear on data (decomposition, storage, tenancy and the like), by path; for `fullstack` the
   storage concern's playbook excerpt (`python3 scripts/playbook.py excerpt storage > plan/adr-excerpts/storage.md`);
   `target_shape`.
3. **Output contract**: `contracts/data-model/<context>.mermaid`, one `erDiagram`, at least one entity, deviations
   annotated with `%%`.
4. **Boundaries**: no file but the output path; no other context's entities; no structural change that no ADR made.
5. **Done means**: the file declares entities (`validate.py`), and the report lists the structural changes not made,
   the cross-context ids drawn and the entities marked internal.
6. **Model + tier**: as resolved by `routing.py`, stated in the brief.

## The build-lane brief (backend, frontend and infra lanes — G5)

Same six parts. `lane-worker`'s agent file carries the standing rules, so they are not pasted into
each brief (a rule that lives in every brief drifts between them, and the paste cost about 1.2K tokens per
dispatch): the **test cadence** (what to run while building, at the joint run, and on the rerun of failures),
the **long-run rules** (`run_in_background`, `run_phases.py`, what counts as green), the **migration** rules and
the **helper** rules. The cadence is also stated for the orchestrator in `g5-build.md`, "Test cadence within a
slice". `eval/lane_plan.py` checks the agent file still carries each rule. The brief says only what is true
of this dispatch:

- **Joint run:** whether this lane is the one named for the joint run (and so stamps and runs the cumulative
  suite), or not.
- **Migrations:** this lane's migration number (or range) for the slice, `<N>`, if its spec changes the schema.
- **Helpers:** whether this lane may run helper agents.

**The plan and the guards** (part 4). `lane-worker`'s agent file carries the standing rules: work the
task rows of the `PLAN.md` at the worktree root, edit only their Status and Notes, set `Status:
amending` if the spec is wrong, follow a guard's block, and start every shell command with `cd
<worktree> &&`. They are not pasted into each brief, because a rule that lives in every brief
drifts between them. The brief carries what is true of this dispatch, as written:

- You work in `<worktree>` on branch `slice/<Sn>-<lane>`, under the `PLAN.md` at its root. The
  rebuild pipeline wrote that plan from the slice specs the user approved. Your standing rules for
  it, and for the guards that run on this repo, are in your agent file.

Parallelism: dispatch independent lanes/modules in the same turn. On subagent output failing
validation, send it back with the validator error — do not hand-fix, the fix must come from a
run that could have produced it.

**Dispatch** (part 6): a build lane runs as the `build-lane` role, on the agent *and* model
`scripts/routing.py --role build-lane` resolves, passed as `subagent_type` and `model` on the
Agent call. It is `lane-worker`, never `general-purpose`: the standing rules live in the agent
file, and a hand-written stand-in prompt silently drops them.

## The lane-verifier brief (`lane-verifier`, only when the user asks for an audit — G5 step 4b)

A single fresh dispatch, never resumed, and never shown the lane's own report: an audit
that reads the implementer's account of its work is the failure it exists to catch. It is
`lane-verifier`, whose agent file carries its rules and its output contract. The brief is
its handoff, with the paths filled in:

```
PLAN: {absolute path to <worktree>/PLAN.md}
Diff: git -C {worktree} diff {base}   (base = git -C {worktree} merge-base <repo main branch> HEAD; covers committed and uncommitted work)
Files: {git -C {worktree} diff --stat {base}, plus untracked files from git -C {worktree} status --porcelain}
Implementer's test run: {the command the lane reported} → {its pass/fail line}
Return only the verify-contract JSON.
```

Then add one line of pipeline
context: "The spec section of PLAN.md is a module spec approved in a rebuild workbench. Its
acceptance criteria are the task rows. A criterion with a `rule_id` must match that Rule Card's
values, as quoted in the spec." Pass `subagent_type` and `model` exactly as
`scripts/routing.py --role lane-verifier` resolves them.

Read the verdict, which is one JSON object (`{"verdict":"PASS"|"FAIL","issues":[...]}`), and
show it to the user. A FAIL does not start a fix round: what to do with it is the user's call.

## Which model each role runs on

This used to read "route model tiers if the environment supports it: extraction → low tier;
merge/spec → mid; ADR drafting → high" — a rule with no mechanism behind it, describing a state
of affairs that was true of nothing: the four agent files carried no `model:`, so every dispatch
inherited the orchestrator's own model regardless of what this paragraph said.

`scripts/routing.py` is that mechanism. It maps each role to a tier once, resolves the tier
through the project's `.claude/model-routing.json` ladder, and prints the `model` to pass. Run it
once per session (SKILL.md step 4b has the command) and read the values off it — do not re-derive
a tier from the shape of the task, and do not infer a role's rung from the old sentence above.

The tiers it assigns, and the argument for each, are in the script's `ROLE_TIERS`. The shape of
the mapping is worth knowing before you read it: **extraction is not the cheap tier here.**
`validate.py` can tell that a finding is schema-valid but not that it is true, so a wrong
finding that parses ships — which puts the miner on the same footing as the judge, and both at
full effort on a cheaper model rather than the reverse.
