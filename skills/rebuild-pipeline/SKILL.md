---
name: rebuild-pipeline
description: Orchestrates the full product-rebuild pipeline — rebuilding an existing product (OSS reference, a category, or an app the user owns and is replacing on a new stack, e.g. React Native → Flutter) end-to-end, ending in production-ready code, over rspec (the spec), sdlc (the build) and bug-hunter (defect search). Use for starting, resuming or checking a rebuild; any pipeline phase (reference and posture, the rspec spec stages, gates, hidden tests, slice build, G6 parity and routing, production readiness); gate lock/reopen; license posture; being blocked by the PreToolUse hook on a locked artifact; autopilot (run unattended, pause/resume/stop, 5-hour usage threshold); and /rebuild. This is the ONLY skill the user should need to touch — it routes all work to rspec's stages, phase references and subagents.
---

# Rebuild Pipeline Orchestrator

You are the single interface between the user and the rebuild pipeline. The user should
never have to remember phase mechanics, file formats, or which agent does what — that is
your job. Your loop on every invocation: **detect state → report progress → act or ask.**

The pipeline (full rationale in `${CLAUDE_PLUGIN_ROOT}/docs/PLAYBOOK.md` — read it once
per project, not every session):

```
G0 Reference, posture, playbook, budgets; preflight
rspec init → discover → features           ── GATE 1: feature lock
rspec stories → tech (ADRs, contracts)      ── GATE 3: architecture lock (+ adr/ playbook, scaffold manifest)
rspec audit → verify → handoff (slices)     ── GATE 2: slice-plan lock
rspec check; hidden split (holdout.py)      ── GATE 4: contract lock (lock, tests, contracts)
G5 Build, per slice      (sdlc lanes on rspec's criteria)
G6 Boundary, per slice   (open → hidden → equivalence → coverage → bug-hunter → human sample; route.py)
GP Production readiness  ── GATE 5: prod-ready lock (terminal)
```

**What a project decides once, at G0, that later phases read.** `sources.yaml` carries an
`architecture:` block: which **playbook** the stack comes from (`references/playbooks/*.md`, or a path to
one the user wrote) and the rebuild's **target shape** (`fullstack`, or `client-only` when the API already
exists and stays put). Both are cheap to answer at G0 and expensive to discover late: target shape flips the
contract from *drafted* to *transcribed*, and it selects GP's checklist.

**The playbook is the stack, locked with the ADRs.** Before `rspec:tech`, `python3 scripts/playbook.py vendor`
copies the selected playbook to `adr/playbook.md` and its scaffold manifest beside it (`adr/` holds nothing
else; the ADRs are rspec's, in `docs/decisions/`), and its stack line becomes rspec's stack preference. Gate 3
locks `adr/` with the ADRs and refuses without a valid manifest, so the stack a code repo is created from
cannot change under the project when the plugin upgrades. The org default
(`playbooks/web-modular-monolith.md`, Go + Nuxt modular monolith) applies when none is named;
`playbooks/mobile-flutter.md` serves a Flutter client against an existing API.

**Repo creation — `scaffold-repo`.** From G5 on, every code repo is created by this plugin's `scaffold-repo`
skill from the locked scaffold manifest (`adr/playbook.scaffold.json`; a project with no playbook writes
`adr/scaffold.json`). The stack is a Gate 3 fact: Gate 3 refuses to lock a playbook that
declares no manifest, so G5 never meets a stack it cannot create. The skill confirms what the ADRs
decided, asks only what they leave open, waits for approval, runs the stack's official generator, and
proves the five commands pass before the repo counts as created (`references/g5-first-slice.md` step 0).
Never scaffold conversationally and never hand-write a `CLAUDE.md` rules brief into a code repo.

**This plugin wraps sdlc, and both plugins' guards apply to pipeline work.** Claude Code loads a
repo's hooks only when the session started in that repo, and rebuild sessions start in the project's
parent, so the guards are plugin hooks. This plugin's (`hooks/scripts/`): a bash guard, a spec gate,
the injection gate and canary, and the commit gates (the locked-artifact, recorded-flow, autopilot and
runbook guards cover the workbench itself); each code-repo guard judges only a repo listed in the
workbench's `repos.yaml`. sdlc's guardrails and role guard reach a set-up repo below the session (sdlc
2.4 or later). A block naming a guard is that guard's rule, never something to edit around. Each build
lane is an sdlc feature: `lane_plan.py` writes its record from the slice specs the user approved, and
that approval is what the spec gate reads (`references/g5-build.md` step 1b). Build lanes run as this
plugin's `lane-worker` agent, resolved through `scripts/routing.py` (`build-lane`), through sdlc's
Build; each lane's review is sdlc's Review, which you run after the lane reports (`g5-build.md`).

## Orchestration Protocol

Run these steps in order at the start of every session that touches the pipeline.

### Step 1 — Locate the workbench

The workbench repo is the pipeline's state store. Look for `locks/pipeline.yaml` in the
current directory, then in `./workbench/`, then in `./*-workbench/` (where `rebuild_init.py <name>`
creates it, beside the code repos). If no workbench exists, the project hasn't started: offer to
run onboarding (Step 4a).

**Then check which release made it.** The first line the call in Step 2 prints is `locks/pipeline.yaml`'s
`rebuild_major` line: a workbench this release made says `rebuild_major: 3`. One that says `2` or `1` was
made by 2.x or 1.x, and one that prints nothing was made by a 0.x release; **this plugin will not open any
of them**: its scripts, its guards and its pipeline (2.x mined the reference itself, with no rspec spec,
posture or holdout; 1.x lanes work under `PLAN.md`) all differ, and there is no migration. Say so in one
message, tell the user to finish that rebuild on the release that made it (2.x: `product-rebuild` 2.2.0;
1.x: `product-rebuild` 1.6.0; 0.x: `product-rebuild-skills`, the plugin this one replaced), and stop. Do not offer to convert it, copy
scripts into it, or run any gate against it. The guards and `upgrade.py` already refuse it; this is the
one place a person is told why.

### Step 2 — Detect state

Run **one** call, with the workbench root as cwd. Three commands in one call, not three tool turns, because
every turn re-bills the whole context and a session starts this way every time:

```sh
grep -m1 '^rebuild_major' locks/pipeline.yaml; python3 ${CLAUDE_PLUGIN_ROOT}/skills/rebuild-pipeline/scripts/upgrade.py --auto --plugin ${CLAUDE_PLUGIN_ROOT}; python3 scripts/gate.py status
```

The first prints the release check from Step 1, the second brings the tooling up to date (below), and the
third derives the state, after the upgrade so it reflects it. If the first prints nothing, stop at Step 1:
the other two are read-only or refuse such a workbench, so running them did no harm.

`gate.py status` is always the workbench's own `scripts/` copy, never the plugin's. Every script except
`rebuild_init.py` reads and writes cwd-relative paths, and `validate.py`/`parity.py`
use `yamlio.py`, `schemacheck.py` and `_vendor/pyyaml/` from the same directory, so nothing is installed.

**The second command brings the workbench's tooling up to the plugin you are running** — the one exception
to "never the plugin's copy", because the workbench's own upgrader is as old as the rest.
It prints one `TOOLING` line. It copies only the vendored files it can prove are unmodified,
and only when no slice is in progress, no autopilot run is engaged, the tree is clean and no
copy would break an import between scripts; otherwise it defers to a later session start. An
applied upgrade is one commit, followed by `validate` and `gate status`. Relay the line in
Step 3. A `refused` file is a local edit or an unknown-provenance copy: say so and leave it to
the user (`python3 scripts/upgrade.py` shows why). A `FAILS` from validate, or a `gate status
changed`, after an upgrade is the first thing to look at, before any pipeline work.

This prints each gate's state (open/locked, date, artifact hashes) and derives the
**current phase**: the first phase whose entry gate is locked but whose own exit gate
is not. Trust the script's output over your memory of the conversation — sessions
resume days apart.

**One correction on top of it, at the front of the pipeline.** No gate separates G0 from
rspec's first stages — gate-1 closes `rspec:features` — so "first unlocked gate" reports the
rspec stages for every workbench that has been scaffolded, including one whose G0 never
finished. Apply this before routing:

> A workbench with `sources.yaml` filled in but **no `preflight.json`** is in **G0**. Finish
> G0 and run `python3 scripts/preflight.py` (g0 reference has it as the last action).
> A `preflight.json` reading **`Not-ready`** is also still G0: report the blockers from
> `PREFLIGHT.md`, and do not start `rspec:discover` until it reads `Ready` or `Ready-with-gaps`.

Everything else in G0 still proceeds and still commits — `sources.yaml` and
`license-posture.md` are decisions, and none of preflight's blockers changes one. What is
held is rspec's discovery, because it reads and records the reference that preflight says is
not where the workbench thinks it is.

### Step 3 — Report progress, always

Before doing anything, give the user a short progress picture: current phase, what has
been locked (with dates), what the phase needs to exit, and what is blocked behind it.
Keep it to a few lines. The user must never wonder "where are we?".

### Step 4 — Act

Route on the current phase. Read ONLY the matching reference file — they are
per-phase by design to keep context lean:

| Phase | Read | Typical work |
|---|---|---|
| Not started | `references/g0-reference.md` | Onboarding interview, scaffold workbench |
| G0 (scaffolded, no `preflight.json` or Not-ready) | `references/g0-reference.md` | Finish the interview, fill `sources.yaml`, `python3 scripts/preflight.py` until Ready / Ready-with-gaps |
| Toward gate-1 (G0 done) | nothing here: rspec's skills | `rspec:init` in the workbench (rspec's single-repo layout, `docs/`; goal `production`, which a rebuild always is: Gate 1 refuses any other), `rspec:discover`, `rspec:features` (the user approves the list) → Gate 1 |
| Toward gate-3 | the playbook `sources.yaml` names (its stack line) | `rspec:stories`; `python3 scripts/playbook.py vendor` and the stack preference (4d); `rspec:tech`; the ADR approval, which is `rspec:handoff` step 1 → Gate 3 (refuses without the vendored manifest) |
| Toward gate-2 | nothing here: rspec's skills | `rspec:audit`, `rspec:verify` (skipped when `reference.run.kind` is `none`), the rest of `rspec:handoff` (the build plan, ≤ 10 criteria per slice), `rspec:check` (writes `docs/criteria.lock.json`), then `python3 scripts/holdout.py split` (draws the hidden tests into a repo in the per-user data folder, named only in its `holdouts.json`; never name that path in a brief) and only then commit the workbench: `docs/acceptance/` stays git-ignored until the split, because a commit before it puts the hidden tests in the history every lane holds as a submodule (the split refuses when one is there) → Gate 2 (refuses before the split) |
| Toward gate-4 | nothing here: rspec's skills | review the contracts and tests → Gate 4 (records the split; MVP level 2 ≥ 90% unless `strict`, or the user's signed reason) |
| G5 | `references/g5-build.md` (plus `references/g5-first-slice.md` for the first slice's repo checklist, an inbound-webhook slice, and the S1 runbook) | The slice loop (4e): step 0, lanes, spec questions; the between-slices sequence at the end of it |
| G6 | 4f below (and `references/g6-parity.md` for the parity report and slice review) | `boundary.py <Sn>`, cheapest step first; `route.py`; the human sample |
| GP | `references/gp-production.md` | rspec's readiness checklist, `gp.py nfr` (each NFR's verification run on the production candidate), Gate 5 review |

**Budgets and cost (05 P9).** G0 shows the user `rebuild.yaml`'s budgets once (parallel lanes, recorders,
hunters per slice, bug-hunter tokens per slice, fix rounds) and they edit it there; the scripts that spend each
one read it. After every subagent or plugin run you orchestrate (rspec stages, lanes, reviews), record it:
`python3 scripts/cost.py add [--slice <Sn>] --stage <stage> --plugin <p> --agent <a> --tier <t> --wall-s <n>
--turns <n> --tokens-in <n|null> --tokens-out <n|null> --result <r>`, with the numbers the host reported (never
guessed). bug-hunter writes its own through the `--cost-log` boundary.py names. `boundary.py` prints the slice's
cost by stage.

**4a — Onboarding (no workbench).** Interview the user: which reference product, why,
distribution intent (this decides license posture), whether the reference is third-party or
an app they already own, and the `architecture:` block — target shape and playbook (see g0
reference for all of it). Then scaffold:
`python3 ${CLAUDE_PLUGIN_ROOT}/skills/rebuild-pipeline/scripts/rebuild_init.py <project-name>`
and walk the user through the generated `sources.yaml` and `license-posture.md`. Before
leaving G0, give the workbench a remote and push it (g0 reference has the commands) —
visibility follows the posture just decided.

**4d — rspec owns the spec (05 P2).** From G0's end to Gate 4 every step is an rspec stage: call it
with the Skill tool (`rspec:init`, `rspec:discover`, `rspec:features`, `rspec:stories`, `rspec:tech`,
`rspec:audit`, `rspec:verify`, `rspec:handoff`, `rspec:check`) from the workbench root, and let it run its
own agents, questions and checks. Never do a stage's work here, and never re-implement one. Which stage is
next, and what it still has pending, is the `rspec:` line `gate.py status` prints from rspec's own
`progress.py`; `rspec: not run: <reason>` means rspec is not installed or not found (set
`RSPEC_PLUGIN_ROOT`), and no stage is guessed at. The gates still belong to this repo and still need the
user (Step 5); their order is rspec's: 1, 3, 2, 4. **Before `rspec:tech`**, run `python3 scripts/playbook.py
vendor` (commit `adr/`), and when `docs/rspec.json`'s `stack` is empty, write the vendored playbook's stack line
there: rspec's stack ADR weighs it as a preference against `deploy`. Never overwrite a stack the user gave. List
the playbook's concerns and decide-before order to the user at Gate 3: rspec's ADRs should cover them.

**4e — The slice loop from rspec's criteria (05 P5).** Slices are rspec's (`docs/build-plan.md`, Gate 2), so
there are no slice specs to write. Per slice, from the workbench root:
1. **Step 0:** `python3 scripts/lane_plan.py step0 <Sn>`. Every criterion needs a level 2 test or rspec's
   reason for level 1; for the ones it names, run `rspec:verify --only <features>` and check again.
   `lane_plan.py` opens no lane of a slice that fails it.
2. **Lanes:** `python3 scripts/lane_plan.py <Sn> <lane> --worktree <path> --features <F-…,F-…>
   --approved-by "<name>"`. It writes the lane's sdlc feature with ACs citing the criterion IDs (sdlc's
   spec-backed mode), copies the lane's open recorded tests into its `acceptance/` (each checked against
   the workbench manifest's sha256) and the lock to `.rebuild/criteria.lock.json`. Hidden tests never reach
   a lane, and its brief never names the holdout. At most `rebuild.yaml` `budgets.parallel_lanes` lanes
   (default 3) are open per slice.
3. **Spec questions:** a lane asks with sdlc's `state.py question`, which blocks its part. Collect them with
   `python3 scripts/lane_plan.py questions <Sn>` (`plan/spec-questions/<Sn>.md`), run `rspec:amend` on the
   batch (the user approves any change to an MVP criterion's `then`), re-verify, then `lane_plan.py refresh
   <Sn> <lane>` for each lane it touched; the lane's `state.py questions` unblocks it.
4. **The bundle is read-only:** a committed file under `docs/acceptance/` changes only after `python3
   scripts/flows.py unlock --acceptance --reason "…"` (and `relock --acceptance` after); the flow guard
   blocks it otherwise. A wrong recorded test is a spec question, never an edit.
At G6, `python3 scripts/holdout.py run <Sn>` (with `ACCEPT_BASE_URL` at the slice build, `--repo <code
repo>` for Playwright tests) runs the slice's hidden tests; its report names criteria and observed
behaviour only, so it is safe to pass to a lane.

**4f — G6 at each slice boundary (05 P6, P7).** From the workbench root, with `ACCEPT_BASE_URL` at the slice
build (rspec verify leaves it at the reference; `boundary.py` and `holdout.py run` refuse the address in
`sources.yaml` `reference.run.base_url`): `python3 scripts/boundary.py <Sn>`. It runs the open suite (each failure re-run once; a pass on the
re-run is flaky, not a finding), the hidden suite, equivalence (posture `observe` or `own-code`), parity and
the slice review, then bug-hunter and the human sample, and stops at the first step that leaves a build-defect
or spec-gap open. Then:
- **Route:** `python3 scripts/route.py <Sn>` writes fix round N (`plan/fix-rounds/<Sn>-r<N>.md`):
  build-defect and test-defect → a fix lane per feature (`lane_plan.py <Sn> fix-r<N>-<feature> --fix <N>
  --findings <ids>`); spec-gap → `rspec:amend` (the user approves an MVP `then`), re-verify, then a fix lane;
  reference-defect → the user: copy it or add a departure; flaky, environment → fix the harness yourself.
  `route.py <Sn> --close <ids>` once a round fixes them. The same findings open the next round only once the
  round's attempt is recorded: archiving its fix lane does it, and a fix you made on the workbench side (the
  harness, an amend, a departure) is `route.py <Sn> --attempted "<what you fixed>"`. A third round is refused:
  ask the user.
- **bug-hunter:** run the command `boundary.py` prints, then `python3 scripts/boundary.py hunted <Sn>`.
- **Human sample:** `python3 scripts/boundary.py sample <Sn>` draws 2–3 features into
  `plan/slice-reviews/<Sn>.md`; the user compares them with the running reference and writes `agree` or
  `differs: <what> (class: …)`. Never fill it in yourself, under autopilot or not.
- **Departures:** every accepted difference is one entry in `docs/departures.yaml`, read by every check;
  `equiv.py accept … --by` and `flows.py unlock --acceptance --weakens --criteria … --by` write them, and only
  the user decides one. The registry is append-only from the gate-1 lock, not hashed: gate-1 refuses to lock
  while any entry is proposed, lacks `decided_by` or has an ID that is not `D-<nnn>`, and otherwise records every
  entry. Never edit or remove a recorded entry (validate.py and gate-5 refuse it, and no departure explains
  anything until it is restored); add a new departure instead. A gate-1 lock whose `artifact_hashes` lists
  `docs/departures.yaml` (taken before this rule) refuses additions: reopen and lock gate-1 again first.
The boundary passes when the open and hidden suites are green or explained, no high finding is open,
bug-hunter has run and the sample is recorded.

**4b — Delegation.** You orchestrate; subagents execute. The spec side is rspec's stages, which run their
own agents. The one agent of this plugin is the build lane (`agents/lane-worker.md`), briefed per
`references/subagent-briefs.md`; its reviews are sdlc's agents. Run independent lanes in parallel. Do the
work inline only when it is small or when subagents are unavailable in the current environment.

**Resolve the model ladder once per session, before the first dispatch**, from the workbench
root:

```sh
python3 scripts/routing.py --agents ${CLAUDE_PLUGIN_ROOT}/agents
```

It prints, per role, the `tier`, the `model` to pass on the Agent call, the `effort` its agent
file pins, and `why` that rung. **Pass `model:` explicitly on every dispatch**, even when it
matches the agent file's own frontmatter, so the brief and the actual run cannot disagree. Cache
the result for the session — the ladder is a project setting, not a per-dispatch decision, and
re-running it between every fan-out is pure noise.

**Relay any non-empty `warnings` to the user** and do not otherwise act on them. A malformed
`.claude/model-routing.json` degrades to the `balanced` default rather than failing, so a
config the user believes is active but is not would otherwise be invisible. Effort warnings are expected
(`build-lane` under `frontier`) and are not a problem to fix: effort is pinned per role and is not movable at
spawn time (`scripts/routing.py` has the argument).

**4c — When intent is ambiguous, ask — with options.** If the user's request could mean
several things ("continue" during G5 could mean: next module in this slice, start next
slice, or run parity), present the concrete options rather than guessing.

### Step 5 — Gate protocol (never self-approve)

Gates are human decisions. When a phase's exit criteria are met:

1. Run `python3 scripts/validate.py` from the workbench root (the workbench's own files: overlays,
   posture, the scaffold manifest, lock integrity), and for gates 1 to 4 `rspec:check` (rspec's spec).
   The semantic read of the spec is rspec's audit: its three fresh auditors (facts, coverage,
   consistency) run before handoff, and their reports are in `docs/audit/`. Bring what they flagged to
   the review; a finding they marked Important and nobody fixed is a reason to wait, never a detail.

2. Present a **gate review** to the user: what is being locked, the key decisions inside
   it, open risks, what rspec's audit flagged, and what becomes immutable afterward.
3. Only after explicit user approval, run `python3 scripts/gate.py lock <gate-id> --by "<who approved, and
   how>"` (`"Tam Mai, in this session"`, `"Tam Mai, relayed by the coordinator"`). Without `--by` the
   lock records the shell's `$USER`, which says who ran the command, not who approved.
4. **Push the lock commit *and* its tag**: `git push && git push --tags`. Both are needed —
   `git push` sends no tags, and `--follow-tags` does not help because gate tags are
   lightweight. The tag is not a label: code repos pin this workbench as a submodule at
   `gate-N/vN`, so one that never leaves the machine either breaks their checkout or leaves
   them silently building against the previous contract. Nothing pushes on your behalf.
5. Never lock a gate on your own initiative, and never edit files under a locked gate's
   `protects:` paths — the PreToolUse hook will block you, and the correct response to
   that block is to propose reopening the gate to the user, not to work around it.
   This holds under autopilot too: a run reaching a gate writes its review to
   `plan/gate-reviews/gate-N.md` and stops there (Step 6).

Reopening (`gate.py reopen <gate-id> --reason "..."`) is allowed but is a formal,
logged event; require the user to state the reason.

### Step 6 — Autopilot, if the user asks for it (opt-in, off by default)

Autopilot runs the mechanical stretches between gates unattended — rspec's stages (under rspec's own
autopilot rules), per-slice lanes, G6 boundaries — checkpointing to disk after every unit, and **halting at
every gate**. It changes nothing about Step 5: it never locks a gate, and the list of
non-gate human decisions it must also stop for is in the reference file.

When the user asks for autopilot, read `references/autopilot.md` and follow it. Never
engage without running `python3 scripts/autopilot.py preflight` and getting an explicit
confirmation of the brief — the word "autopilot" is a request to be told what a run would
do, not consent to run it.

If `plan/autopilot.yaml` exists with `status: paused`, say so in Step 3 along with why it
stopped, and offer to resume. Its `engaged_phase` and `paused.next_action` are breadcrumbs
for a human reading the file — `gate.py status` remains the authority on where the project
actually is.

### Step 7 — Pause safety check (before ending a session)

When the user signals they're pausing, stopping, or ending the session — or you notice a
natural stopping point (a slice just finished, a gate review just landed) — run:
`python3 scripts/pause_check.py` (from the workbench root)

This is NOT one of the five hash-pinned gates — it locks nothing, has no gate-guard
enforcement, and is safe to run any number of times. It reports, across the workbench and
every repo registered in `repos.yaml`: uncommitted/untracked git changes, work that has not
left the machine (no remote, unpushed commits including on a detached HEAD, unpushed tags,
stash entries), any gate left mid-decision (reopened but not re-locked), AC flow assertions
left unlocked (the `parity/flows/` or `docs/acceptance/` guard suspended and never restored), and docker-compose
stacks or host-native dev servers left running. Report
its verdict to the user plainly. If it flags issues, resolve them (commit or explicitly
flag draft work, decide on a reopened gate, stop or consciously keep services running)
before the session ends — don't just relay the warning and move on. It also can't check
one thing by itself: confirm out loud that nothing non-trivial exists only in this
conversation (a draft lane approval, in-flight findings) that hasn't reached disk.

## Conventions (apply everywhere)

- Checkpoint discipline: write in-progress, unlocked work to disk in the workbench
  proactively — a draft lane approval, a gate review, in-flight findings — without waiting to be
  asked. Do this whenever a chunk of non-trivial content only exists in conversation and
  the turn is ending (user signals they're pausing/stopping, or a natural sub-step just
  finished). Draft files on disk survive a new session; chat text does not. This is safe
  because gates protect *locked* artifacts only — draft files can be freely overwritten.
- Artifact-first: every phase output is a schema-validated file in the workbench. If it
  isn't validated, the phase isn't done.
- Evidence rule: no finding without a reproduction (contracts C6: a finding is verified or not routed).
- Propose-before-act: show plans (taxonomy, slice order, ADR decisions, specs) before
  writing them as final artifacts.
- The workbench describes the product; it never contains product code. Code repos are
  created only after Gate 3 and consume the workbench as a read-only submodule pinned
  to gate tags.
- Off-machine by default: every repo this pipeline creates gets a remote at creation time,
  visibility per `license-posture.md` (private unless the posture is `permissive-reference`).
  The pipeline's output is months of decisions that re-running discovery cannot reproduce, so a
  single-disk copy is a real risk, not a hypothetical one — push it, and keep pushing it.
  A remote is for durability; whether the host also runs CI is a *separate* decision, asked
  explicitly at G0 and per repo at G5. For a durability-only remote, disable the host's CI —
  these repos' workflows are written for local or self-hosted execution and fail on a hosted
  runner (private-submodule checkout, unset secrets, gitignored paths), so leaving them
  enabled just emails a failure on every push.
- The slice boundary is the only cheap place to change the plan, so stop there deliberately:
  record progress, run `python3 scripts/boundary.py <Sn>` (archives the lanes, runs G6 cheapest first, says
  whether the upstream re-mine is due), route what it finds, and act on the sequence if it needs acting on.
  Nothing blocks the next slice's lanes but a parked decision they depend on, which is exactly why the
  boundary has to be a habit rather than a mechanism you can lean on.
- Slice ORDER is a logged decision (`python3 scripts/sequence.py reorder ... --reason "..."`), slice
  BOUNDARIES are a gate-2 reopen. Never conflate them, and never hand-edit
  `plan/sequence.yaml` — the file's value is that every change to it carries a reason.
- Tests in G5 run at a fixed cadence (`g5-build.md`, "Test cadence within a slice"): lanes run
  only what they touch while building, the full cumulative suite runs once per slice as the
  joint run, then only its failures re-run. You, the orchestrator, run no tests at all — you
  read the JUnit — and while a lane has a long run open, `scripts/lanes_check.py watch`
  (one background process, `--interval 600`, or 300 while the joint run is open) is what notices when it stops. The
  joint run is one `scripts/run_phases.py` process, so its lane has one wake-up, not one per
  phase.
- All model-facing artifacts are English.

## Context hygiene (the pipeline's main token cost)

Cost here is not output, it is context re-read on every turn: a measured downstream run held a
445k median context for 5,000 turns. So:

- **Never Read `plan/progress.yaml`, `docs/build-plan.md` or `docs/criteria.lock.json` whole.** `grep -n`
  for the slice id or heading, then Read with offset/limit. `pause-check` flags any over 40 KB.
- **One session per unit of work** (a slice stage, a gate review). Checkpoint to `plan/drafts/`,
  run `pause-check`, end the session; resume from `gate.py status`, not from chat memory.
- **Do not dispatch `fork` subagents for pipeline work.** A fork inherits the orchestrator's whole
  context and its model. Use the named agents, which start clean and run on the routed model.
- Redirect long Bash output to a file and read the tail; do not let a build log land in context.
- **End the session when it gets big, attended or not.** At each unit boundary,
  `python3 scripts/autopilot.py status` prints the session's context in tokens (from the status
  line's snapshot — `references/autopilot.md`). Over the limit (default 250k): checkpoint, run
  `pause-check`, and tell the user `/clear`, then `/rebuild`. Autopilot does this itself through
  `check` and a `context-threshold` pause.
- **Keep the orchestrator thin.** A subagent's result reaches you as its short report plus the
  file it wrote; check the file with `validate.py` or a targeted Grep, never by reading it
  whole. A gate review is written to `plan/gate-reviews/` and the chat gets the path and the
  few lines that need a decision. Never paste a subagent's output, a spec, or a contract back
  into the conversation.

## Failure modes to actively prevent

- Leaving non-trivial in-progress work only in chat when a session is ending — persist
  it as a draft file first (see checkpoint discipline above).
- Skipping state detection and acting on stale conversational memory.
- Doing lane work inline that should fan out to parallel subagents.
- Nudging the user toward locking a gate to "make progress" — gates gain value from
  being deliberate. A clean audit is not an argument for locking; it is one input to the
  decision the pipeline keeps manual on purpose.
- Doing an rspec stage's work here (writing stories, ADRs, criteria or tests by hand) instead of
  running the stage: rspec verifies its own spec, and a hand-written piece skips that.
- Editing locked artifacts instead of proposing a reopen.
- Letting the user drift into product code before Gate 3 locks decomposition.
- Carrying a playbook's concern list or section numbers over from another project instead of
  reading the vendored `adr/playbook.md`: §8 means storage in one playbook and auth in another, and
  a plausible-looking wrong section is caught by nothing.
- Creating a code repo by hand — running `npm create` or `go mod init` directly, scaffolding
  conversationally, or writing a `CLAUDE.md` rules brief yourself. Repos come from `scaffold-repo`.
  A stack with no manifest is a Gate 3 failure to fix there, not a reason to improvise at G5.
  The repo is then off the org baseline in ways nothing downstream detects, and the
  governance gates the harness installs are silently absent for the life of the project.
- Trusting codegen from the scaffold's starter `openapi.yaml`. Gate 4's locked contract
  replaces it before any generated type is built on.
- Starting the next slice straight off the back of the last one. Nothing blocks it — the slice
  review is advisory by design — which is why it is listed here instead: the boundary is where
  a reorder is still cheap, and once the next slice starts `sequence.py` refuses one outright.
- Reordering, or proposing a reorder, mid-slice. The finding is welcome; write it to
  `plan/progress.yaml` `notes:` on the slice in flight, where the parity report and the next
  slice review both pick it up. The reshuffle waits for the boundary.
- Writing a slice review by hand, or "summarising" one into chat instead of running the script.
  It is generated from disk on purpose: a composed one is an account of what an agent believes
  it did, and it is exactly the artifact that outlives the session that produced it.
- Ending a session without running the pause safety check (Step 7), or running it but not
  acting on what it flags.
- Engaging autopilot on a partial preflight, or on an inferred yes — "can you autopilot
  this?" asks for the brief; only an explicit approval of that brief starts a run.
- Resuming an autopilot run from `plan/autopilot.yaml`'s `next_action` instead of
  re-deriving the phase with `gate.py status`. It is a breadcrumb written before a pause,
  and the project may have moved since.
- Pushing past the usage threshold because the current unit felt nearly done. That is the
  exact moment the rule exists for, and the hook will block the write regardless.
- Letting a project run for weeks with no remote, then treating "back it up" as a chore for
  later. The cost of the loss grows every phase; the fix takes one command at G0.
- Creating a public remote for a rebuild whose posture does not allow distribution. Pushing
  it publicly *is* distribution, whatever the intent — a copyleft reference makes that a
  licensing problem and a proprietary one a terms problem, so it needs a G0 reopen first,
  not a `--public` flag.
