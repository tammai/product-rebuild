# product-rebuild

> **3.x orchestrates [rspec](https://github.com/tammai/rspec), [sdlc](https://github.com/tammai/sdlc) and
> [bug-hunter](https://github.com/tammai/bug-hunter).** rspec writes and verifies the spec, sdlc builds each lane,
> bug-hunter searches for defects; this plugin locks the gates, keeps hidden tests out of the lanes, runs each slice
> boundary and routes what it finds. It does not open a rebuild 2.x, 1.x or the 0.x plugin this one replaced
> started: finish those on the release that made them (2.x: product-rebuild 2.2.0). There is no migration;
> [docs/MIGRATION-3.md](docs/MIGRATION-3.md) says where each 2.x capability went.

A Claude Code plugin for rebuilding an existing product end-to-end — to learn the full product
development lifecycle by doing it. Point it at a reference product (usually OSS: OpenProject,
Twenty CRM, Webstudio, or a category like "CRM"), and it drives a gated pipeline from the reference
to a verified, production-ready codebase.

**The reference can also be your own product**, which is the case for replacing a legacy app on a new
stack. And the rebuild does not have to own both halves: set `target_shape: client-only` and the existing
backend API stays where it is, a contract the pipeline transcribes and freezes rather than designs. A messy
old React Native app rebuilt in Flutter, backend untouched, is the same pipeline with three fields set
differently at G0.

**You interact with one thing only: the `rebuild-pipeline` skill** (or the `/product-rebuild:rebuild`
command). It detects where the project stands, reports progress, runs rspec's stages, dispatches build
lanes, and stops at every gate to ask for your decision.

The methodology and its rationale live in [`docs/PLAYBOOK.md`](docs/PLAYBOOK.md).

## The pipeline in one picture

![Rebuild pipeline 3.0: G0 reference, posture, playbook and budgets, then a preflight that holds rspec's discovery while it reads Not-ready. rspec's stages produce the spec: init, discover and features (Gate 1 feature lock), stories and tech with the vendored playbook (Gate 3 architecture lock), audit, verify and handoff (Gate 2 slice-plan lock), check and the hidden-test split (Gate 4 contract lock). Then a repeating per-slice loop: step 0, sdlc build lanes on rspec's criteria, spec questions answered by rspec amend; then a slice boundary that runs G6 cheapest first: open suite, hidden suite, equivalence, coverage, bug-hunter and a human sample, with every finding routed to sdlc, rspec, the user or the orchestrator. Out of the loop to GP production readiness and Gate 5.](docs/img/pipeline.png)

Green is automated or agent work; amber is a gate — a human decision that locks. Dashed amber is a human
step inside the loop. The loop is the shape of the build: every slice ends deployed, then stops at a
boundary before the next one starts.

Three ideas carry everything:

1. **Verification sits with the producer.** rspec verifies its own spec against the running reference,
   sdlc verifies each lane's tests, bug-hunter reproduces each finding with a fresh verifier. This plugin
   adds only what needs two of them at once: locking, hidden tests, parity and routing.
2. **Gates, not momentum.** Five points where the pipeline deliberately stops for a human decision, each
   locking rspec's artifacts by hash. Locked artifacts are enforced — a hook blocks edits to them.
3. **The reference is the oracle.** Agreement between agents is never evidence. A check counts when it
   compares against the running reference, a recorded test or a cited source — which is why some tests are
   hidden from the lanes, and why a person compares a sample of each slice with the reference.

## Install

```bash
# product-rebuild has its own marketplace; its dependencies come from theirs, so add all four
/plugin marketplace add tammai/sdlc
/plugin marketplace add tammai/rspec
/plugin marketplace add tammai/bug-hunter
/plugin marketplace add tammai/product-rebuild
/plugin install product-rebuild@product-rebuild

# or for local development, load your working copies for one session:
claude --plugin-dir /path/to/sdlc --plugin-dir /path/to/rspec --plugin-dir /path/to/bug-hunter --plugin-dir /path/to/product-rebuild
```

Claude Code installs sdlc, sdlc-extras, rspec and bug-hunter itself, from their marketplaces, which is why
each must be added. Without them this plugin is disabled with a dependency error (`claude plugin list`
names it).

Requires Python ≥ 3.9 (standard library only: there is nothing to `pip install`, and the YAML reader ships
inside the plugin), git, and Docker (you will run the reference product locally — it is what the tests are
recorded against). The code repos you scaffold at G5 need whatever their own stack needs (Go, Node,
Flutter), and the scaffold tells you before it starts if a tool is missing.

## Walkthrough: start to finish

### 1. Start (G0)

In any directory, say **"start a rebuild project"** or run `/product-rebuild:rebuild`. The skill interviews
you:

- **Which reference?** Name a product, or a category — it proposes candidates.
- **Distribution intent and posture.** `license-posture.md` records the licence decision; `sources.yaml`
  `reference.posture` records who may read the reference: `strict` (the spec side only observes behaviour),
  `observe` (the default for a third-party reference: the spec side may also read the code) or `own-code`
  (the default for your own app: build lanes may read it too). Which posture a licence allows is your call.
- **What is being rebuilt, and against which playbook?** `target_shape` (`fullstack` or `client-only`) and
  `playbook` (a registry entry, a file of your own, or `none`). The playbook gives the stack and the scaffold
  manifest every code repo is created from.
- **Budgets**, shown once in `rebuild.yaml`: parallel lanes, recorders, hunters and bug-hunter tokens per
  slice, fix rounds.

It scaffolds your **workbench** (`<name>-workbench/`), and `python3 scripts/preflight.py` proves the
reference builds and runs at the pinned commit before anything reads it.

### 2. The spec (rspec), Gates 1, 3, 2, 4

The skill runs rspec's stages in the workbench and never does their work: `rspec:init`, `discover`,
`features` (you approve the list → **Gate 1**), `stories`, `tech` (the playbook is vendored to `adr/` first
and its stack is rspec's preference; you decide each ADR → **Gate 3**), `audit` and `verify` (tests recorded
against the running reference), `handoff` (vertical slices of at most ~10 criteria), `check`. Then
`holdout.py split` hides 25% of each slice's recorded tests in a repo beside the workbench that no lane can
read, before the bundle is first committed (so no hidden test is ever in the workbench's history), then
**Gate 2** locks the slices and **Gate 4** locks the contracts, the criteria lock and the test bundle (refusing, under
`observe` and `own-code`, while fewer than 90% of MVP criteria have a recorded test, unless you sign a reason).

### 3. Build (G5) — per slice

Step 0 holds a slice until each criterion has a recorded test or rspec's reason. Each lane is an **sdlc
feature** in spec-backed mode: `lane_plan.py` opens it with ACs citing rspec's criterion IDs, its open tests
and a lock copy, and sdlc's Build proves every criterion red then green. A lane that finds a criterion wrong
asks a spec question; the slice's questions go to `rspec:amend` in one batch. Code repos are created by this
plugin's `scaffold-repo` skill from the locked scaffold manifest.

### 4. The slice boundary (G6)

```bash
python3 scripts/boundary.py S3
```

Cheapest step first, stopping at the first that leaves a build defect or spec gap open: the open suite
(each failure re-run once), the hidden suite, equivalence (recorded traffic replayed, under `observe` or
`own-code`), coverage and the slice review, bug-hunter, and a **human sample** — 2–3 features you compare with
the running reference. `route.py` sends each reproduced finding where it belongs: a build defect to an sdlc
fix lane, a spec gap to `rspec:amend`, a reference defect to you, a flaky test to the orchestrator. Every
accepted difference is one entry in `docs/departures.yaml`, read by every check.

### 5. Production readiness (GP) and Gate 5

One checklist, rspec's `production-readiness.md`, with **evidence produced by doing**: each NFR's stated
verification run against the production candidate (`gp.py nfr`), a backup restored for real, an incident drill
from the runbook, each with the name of who performed it. **Gate 5** refuses while a hidden test failed or did
not run, a red equivalence trace is unexplained, a high finding is open, a departure is only proposed, or an MVP
criterion is below level 1. Locking it is the finish.

## Knowing where you are

Ask the skill "where are we?" anytime, or run in the workbench:

```bash
python3 scripts/gate.py status        # gate states, current phase, and rspec's own progress
python3 scripts/validate.py           # overlays, posture, scaffold manifest, lock integrity
python3 scripts/parity.py             # coverage of rspec's feature list into parity/<date>.md
python3 scripts/slice_review.py S3    # the between-slices standing report (advisory)
python3 scripts/sequence.py status    # execution order: what's frozen, what's orderable now
python3 scripts/pause_check.py        # safe to stop? (includes what hasn't been pushed off-machine)
python3 scripts/autopilot.py preflight   # ready to run unattended between gates?
```

## Autopilot

Say **"autopilot"** and the skill checks the project is in a safe state, tells you exactly what it would run
and where it would stop, and waits for a yes. It runs rspec's stages under rspec's own autopilot rules, lanes
under sdlc's, and boundaries, writing each result to disk and committing before the next. It **halts at every
gate**, and **parks** what only you may decide — a feature drop, a departure, the human sample, a production
deploy, Gate 5 — blocking only what depends on it, so the rest of the slice goes on.

It watches the clock: at 80% of your 5-hour usage window a hook pauses it — saves, commits, pushes, runs the
pause check. It watches its own context too: past 250k tokens it stops at the next unit boundary and asks you
to `/clear` and `/product-rebuild:rebuild`. The 5-hour figure reaches it through your status line only;
`autopilot.py preflight` prints the block to add if it is missing.

**Plugin updates reach your workbench by themselves.** Each workbench carries its own copy of the scripts and
schemas. At session start the skill brings that copy up to the plugin you're running: only files it can prove
you never edited, only between slices, with autopilot off and a clean tree, as one commit.

## What's in this plugin

```
.claude-plugin/plugin.json      manifest (depends on sdlc, sdlc-extras, rspec, bug-hunter)
commands/rebuild.md             /product-rebuild:rebuild — run or resume the pipeline
skills/rebuild-pipeline/        THE skill you interact with
  SKILL.md                      orchestration protocol (state → report → act, gate rules)
  references/                   G0, G5, G6, GP and autopilot detail, loaded only when that phase runs
  references/playbooks/         the architecture-playbook registry: stack and scaffold manifest per playbook
  schemas/*.schema.json         progress, sequence, lock, preflight and autopilot schemas
  scripts/rebuild_init.py       workbench scaffolder
  scripts/gate.py               gate status / lock / reopen (hashes + tags), on rspec's artifacts
  scripts/validate.py           the workbench's own files, and lock integrity (also in CI)
  scripts/playbook.py           vendors the playbook and its scaffold manifest to adr/; their checks
  scripts/holdout.py            the hidden tests: split at Gate 4, run at G6
  scripts/lane_plan.py          step 0, a lane's sdlc record from rspec's criteria, spec questions, archive
  scripts/boundary.py           G6 cheapest first, the human sample, the re-mine reminder
  scripts/route.py              routes each finding by class into fix rounds
  scripts/departures.py         the one departures registry every check reads
  scripts/equiv.py              record and replay request traces against the legacy system
  scripts/parity.py             coverage of rspec's feature list + AC pass rate from the suite's JUnit
  scripts/slice_review.py       the between-slices standing report (generated, advisory)
  scripts/sequence.py           slice execution order over rspec's build plan, logged reorders
  scripts/flows.py              unlock/relock the read-only recorded tests, with a logged reason
  scripts/gp.py                 NFR evidence for GP
  scripts/cost.py               contracts C7 cost lines per slice
  scripts/acsuite.py            JUnit reader shared by parity and slice-review; counts a rerun once
  scripts/lanes_check.py        is a build lane still working? (`watch`, `stamp`)
  scripts/run_phases.py         a several-phase test run as one tracked background process
  scripts/pause_check.py        is it safe to pause the session? (advisory, not a gate)
  scripts/preflight.py          does the reference actually build and run at the pinned commit?
  scripts/upgrade.py            bring a workbench's vendored scripts up to the plugin you are running
  scripts/autopilot.py          unattended runs: preflight / check / engage / park / blocked / disengage
  scripts/routing.py            which model each role dispatches on (.claude/model-routing.json)
  scripts/yamlio.py, schemacheck.py   the YAML and JSON-schema readers (over a vendored PyYAML)
skills/scaffold-repo/           creates each code repo from the locked scaffold manifest
agents/lane-worker.md           the build-lane agent (its reviews are sdlc's agents)
hooks/                          PreToolUse guards: locked artifacts, read-only recorded tests, the
                                autopilot usage threshold, the build runbook; the code-repo guards (bash,
                                spec gate, injection gate, commit gates), which judge only repos listed in
                                a workbench's repos.yaml; the reference guard; a PostToolUse injection
                                scan; and a SessionStart canary seed
contracts/v1/                   the shared contracts the four plugins vendor byte-identical
docs/PLAYBOOK.md                the methodology
docs/MIGRATION-3.md             where each 2.x capability went
```

**The reference guard is a guard, not a sandbox.** A build lane never reads the reference under `strict` or
`observe`, and never the hidden tests under any posture, and writes only inside its own worktree.
`hooks/scripts/reference_guard.py` denies a lane's Read, Grep, Glob, Bash and PowerShell calls that reach those
paths (a recursive search or glob from a directory above them included) and its writes into the workbench. It
sees paths written in the call; a path computed at run time, or a script that opens the file itself, gets past
it. The build under test also sees a hidden test's requests when G6 runs it. Use `strict` for a sensitive
reference, and check the guard's denials in the end-to-end runs. A workbench that committed its bundle before
the split (any 3.0.0-rc.1 workbench past Gate 2) has the hidden tests in its history: `holdout.py split` now
refuses there, and that history must be rewritten before lanes hold the workbench.

## Design rules the plugin enforces (so you don't have to)

- **No silent pass.** A check that cannot run says `not run: <reason>`, and no gate accepts that as a pass.
- **Hidden tests stay hidden.** They live outside every code repo, the guard denies them to lanes, and a G6
  report names the criterion and what the build did, never the test.
- **One registry of accepted differences.** `docs/departures.yaml`; only a person decides an entry.
- **The stack is locked with the ADRs.** Gate 3 hashes the vendored playbook and its scaffold manifest, so a
  plugin upgrade cannot change what a code repo is created from.
- **Locked means locked.** The hook blocks edits under a locked gate's paths; the escape hatch is a formal,
  logged reopen with a reason. That hook matches `Write|Edit|MultiEdit` only: a shell redirect or `sed -i`
  through Bash is not intercepted, and `validate.py`'s locked-hash check is what catches that drift.
- **Recorded tests are read-only.** Loosening an assertion takes `flows.py unlock --acceptance --reason`, a
  logged decision, and a weakening is written as a departure.
- **Gates are yours.** The skill never locks a gate on its own initiative — including on autopilot.
- **The workbench never contains product code.** It describes the product; code repos consume it one-way,
  pinned at gate tags.
- **Every slice ships.** Deployment is part of the definition of done.
- **The work leaves the machine.** Every repo gets a remote when it is created, private unless the license
  posture says otherwise, and the pause check tells you when something still hasn't been pushed.

## FAQ

**Can I use this for a commercial competitive product?** It's built for rebuild-to-learn. The posture step
forces the right questions, but competitive-intelligence workflows are out of scope.

**What if I disagree with a locked decision later?** Reopen the gate with a reason —
`python3 scripts/gate.py reopen gate-3 --reason "..."`. It's logged, and history stays honest.

**Multiple projects?** One workbench per project, always.

**Can I rebuild my own legacy app?** Yes: `reference.kind: own-code`, `reference.upstream: frozen`, posture
`own-code`. The running instance is the app you already have, and the upstream re-mine is off. A frozen
reference is a permanent arbiter for "what did the old app actually do here", so keep it *installable* for
the life of the project.

**Can it rebuild only the client, against an API we are not touching?** That is `target_shape: client-only`
with the `mobile-flutter` playbook (or your own): Gate 4 locks a *transcription* of the existing API rather
than a design.

**None of the shipped playbooks fit my stack.** Write one — a Markdown file with a frontmatter block and a
scaffold manifest; [`references/playbooks/README.md`](skills/rebuild-pipeline/references/playbooks/README.md)
has the format. Gate 3 refuses a playbook with no manifest, so a stack nothing can scaffold fails there, not
at G5. With `architecture.playbook: none` you write `adr/scaffold.json` yourself.
