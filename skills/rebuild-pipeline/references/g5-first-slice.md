# G5, first-slice and one-off steps

Read this when the first slice starts, when a slice's deploy criterion needs the outside world to reach in, and
at the S1 boundary. `g5-build.md` is the per-slice loop and is all you need for every other slice. These three
blocks were part of it until 1.4.0 and moved here so that the orchestrator does not carry them on every turn of
every slice; the hook messages, scripts and docs that point at them name this file.

## 1. The repo checklist: the first time a code repo is created

**The first time a code repo is created**, do all six of these — the repo is not set up
until they are:

0. **Create it with the `scaffold-repo` skill, never by hand.** From an **empty directory**, invoke
   `scaffold-repo` (this plugin's skill; its procedure is in `skills/scaffold-repo/SKILL.md`). It reads
   the scaffold manifest Gate 3 locked (`adr/playbook.scaffold.json`, or `adr/scaffold.json` for a
   project with no playbook), takes the stack from the locked ADRs, asks only what they leave open
   (an organisation name, a package name), shows you a proposal, and waits for your approval. Then it
   runs the stack's own official generator, writes the five commands, path-scoped rules, git hooks,
   CI and a thin `CLAUDE.md` pointer, and **runs the five commands on day one**: every one must exit 0
   before the repo counts as created. Never scaffold conversationally and never hand-write the
   project files a generator would have produced: a repo made by hand diverges from every other repo
   the pipeline made, and its `lint` is the first thing to go missing.

   Profile follows Gate 3's stack ADR, not a fresh decision: `--choose api=go` is what the locked
   ADR says, and a package with several options in the manifest (Go or Fastify, Nuxt or Next) is
   answered from the ADR, never from what you would prefer.

   **A stack the playbook cannot scaffold never reaches G5.** Gate 3 refuses to lock a playbook that
   declares no manifest, so the situation "an empty directory plus a stack nothing can create" cannot
   arise here. A project that chose no playbook (`architecture.playbook: none`) writes its own
   `adr/scaffold.json` alongside its stack ADR, in the same format and held to the same check.

   **What the scaffold is, and is not.** It is a skeleton: the generator's output, strict typing, a
   test runner, a linter, and one passing smoke test per package, pinned so CI matches local. It is
   not a feature kit. It has no auth, no database, no Docker and no module layout beyond what the
   playbook's own manifest seeds; the first slice's lane builds the first real module under a spec
   you approved. (Before 1.0.0 the scaffold arrived with a working auth kernel, and recording it as
   delivered-by-scaffold was a bookkeeping step. There is nothing to record now.)

   Everything else in this checklist applies as written: register in `repos.yaml`, remote with
   posture-matching visibility, confirm `pause-check` sees it, decide what the remote is for.

   Three things about the order, each of which breaks the run if got wrong:
   - **Scaffold into the directory while it is still empty, then add the workbench submodule.**
     Official generators (`go mod init` aside) refuse or prompt on a non-empty directory, and a
     submodule is a non-empty directory. Submodule after, always.
   - **The scaffold makes its own commits** (`chore(scaffold): <step>`), so step 2's
     `gh repo create --source . --push` runs *after* it, against a repo that already has history.
   - **The repo is unguarded until step 1 registers it.** The plugin's guards judge only repos listed
     in the workbench's `repos.yaml`, so register it before any lane works there.

1. **Register it** in the workbench's `repos.yaml` (`name` + `path` relative to the
   workbench root). `scripts/pause_check.py` reads this list; an unregistered repo is
   invisible to it and never checked before a session pauses.
2. **Give it a remote**, visibility per `license-posture.md` — private unless the posture is
   `permissive-reference`:
   `gh repo create <repo-name> --private --source . --push`
3. **Confirm it is actually covered**: run `python3 scripts/pause_check.py` from the workbench and check
   the new repo appears by name in the report. Registering is not the same as being checked —
   a one-character typo in `path:` (or a path relative to the wrong directory) shows up as
   `registered in repos.yaml but this path does not exist … — nothing about this repo was
   checked`. Without this confirmation nothing else ever catches it, and the repo goes
   unchecked for uncommitted and unpushed work for the rest of the project.
4. **Decide what the remote is for, and say it out loud.** Two different things get called
   "the repo has a remote":
   - *Durability only* — CI runs locally or on your own infrastructure. Then **disable Actions
     on the remote**, or every push emails you a failure:
     `gh api -X PUT repos/<owner>/<repo>/actions/permissions -F enabled=false`
   - *Also running CI on the host* — then the workflow has to actually work there, which for
     this pipeline's repos it does not by default. See the trap below.

**The private-submodule trap.** A code repo that checks out with `submodules: true` will fail
on GitHub Actions the first time it is pushed, with `fatal: repository '...workbench' not
found`. That is not a missing repo and not a bad token — `GITHUB_TOKEN` is scoped to its own
repository, so a private sibling reads as 404. Fixing it properly means a read-only deploy key
on the workbench plus a manual `git submodule update` over SSH (which preserves the gate-tag
pin; a second `actions/checkout` of the workbench does not). Only worth doing if CI on the host
is actually wanted — for a durability-only remote, disabling Actions is the honest answer.

Two more reasons a workflow written for local execution fails on a hosted runner: it needs
secrets that were never set there, and it reads paths that `.gitignore` keeps out of the repo
(deploy state files are the usual culprit). Check both before assuming a green CI is one fix
away.

If the repo pins the workbench as a submodule with a **relative** URL (`../<name>-workbench`),
push the workbench remote first and keep both repos under the same owner: the relative URL
then resolves against the code repo's own remote, so a fresh
`git clone --recurse-submodules` works with no per-machine configuration.

5. **Write `.rebuild-workbench` at the repo root**, holding the path to the **live**
   workbench — one line, absolute, or relative to this repo:

   ```sh
   echo "/abs/path/to/<name>-workbench" > .rebuild-workbench
   git add .rebuild-workbench && git commit -m "chore: point at the rebuild workbench"
   ```

   This is how `runbook_guard.py` finds the workbench, and it cannot use the submodule for
   it: the submodule is checked out at a **gate tag**, so its `plan/progress.yaml` is frozen
   at Gate 4 and can never know which slice is in progress — slices happen after that tag.
   The marker is the live pointer; the submodule is the pinned contract. Both, for different
   jobs.

   A repo without the marker is simply unguarded — the hook fails open. That is the correct
   behaviour for every repo in the world that is not part of this project, and it is also why
   writing the marker is a checklist item rather than something inferred.

## 2. The first slice whose deploy criterion needs the OUTSIDE WORLD to reach in

Every deploy criterion up to that point is outbound — the rebuild calls a provider — and
`localhost` serves it fine. The first inbound one (a webhook delivery, an OAuth redirect
that must resolve, a CI runner posting a result) needs something structurally different,
and it is worth naming before the slice rather than discovering mid-verification:

- **A public origin, as configuration.** The URL a provider is told to call has to be
  built from a configured base, not assembled from a request or defaulted to localhost. A
  plausible-looking default is worse than an absent one: registration succeeds and the
  silence afterwards has to be debugged.
- **A tunnel for local verification**, and it is not the same switch as any
  "allow loopback" flag the outbound side has. That one governs where *we* deliver to;
  this is where a *third party* delivers to, and loopback is never a valid answer.
- **A provider-side registration path.** Something must create the subscription and store
  whatever verifies its deliveries. Check it exists — this is the read-with-no-writer trap
  in `g4b-contracts.md`, and the inbound leg is where it hides best, because the receiver
  looks complete on its own.
- **Watch the credential's shape.** A machine credential presented by CI usually is not a
  bearer token, and sending it as one produces a 401 that reads like an infrastructure
  problem from inside a CI job. Check the scheme before blaming the tunnel.

## 3. The build runbook: written after S1, amended at every boundary after

**After S1: write `plan/BUILD_RUNBOOK.md`.** S1 is where the locked contracts, the harness
scaffold and the reference's quirks first meet each other, and until this file exists none of
what it taught is anywhere S2's agents will read. Write it **from what the S1 lanes reported**,
not composed from memory — the same rule as the slice review, for the same reason: a runbook
that is a recollection of a build is a recollection, and it will be read as fact by an agent
that was not there.

Sections are fixed, so a later reader knows where to look and a later writer knows where to add:

```md
# Build runbook — <project>

Written at the S1 boundary from what the S1 lanes reported. Required reading for every
backend, frontend and infra lane from S2 on (`runbook_guard.py` enforces it). Append
amendments; never rewrite.

## Codegen from contracts/
How it was invoked, verbatim. What it got wrong, and what was done about it.

## Harness quirks
What the scaffold produced that needed adjusting, and why. Anything its CI wrote
that does not work for this project's shape.

## Reference behaviors the spec did not say
What the running instance turned out to do that the spec, the flows and the contracts all
missed. This section is the one that saves the most time and is written last, because it is
only visible in hindsight.

## Test fixtures
How fixtures are built, where they live, what they share, what must never be shared.
Per suite: the wall-clock of one full run, and the share of it spent in per-test setup
(fixture creation, database boot, migrations, sign-up flows) — time one package or spec file
and compare the slowest tests to their assertion work. Setup above half the runtime makes
fixing the harness the next slice's first task. Per-suite exceptions to the test cadence, each
with its reason, go here too.

## Migration order
How migration numbers are assigned across parallel lanes, what the migration tool records
(every version applied, or only the highest), and the command that resets the shared stack
before the joint run. If the tool records only the highest, say so here in one line: a lower
number applied after a higher one is skipped without an error.

## Verification
The checkpoint journey (steps, URL or install link, test account) and how to run each suite
level — unit, integration, the single smoke E2E — with its wall-clock. Update it whenever a
checkpoint slice lands; this is the section a person reads to verify the deploy.

## Deploy prerequisites
What had to exist before the deploy criterion could run at all — credentials, network paths,
accounts, a store listing. Name the ones that turned out to be missing.

## Commands that worked
Verbatim, copy-pasteable, with the directory they run in.
```

**After every later slice: append `## Amendment after S<n>`, dated. Never rewrite.** The
runbook is a record of what was learned and when; rewriting it destroys the sequence, and the
sequence is what tells a reader whether a claim predates the thing they are debugging.
`slice_review.py`'s fifth question puts the diff since the previous boundary in front of you at
exactly the moment to answer it, and records what you did in `plan/progress.yaml`'s
`runbook_amended:` — a boundary that wrote nothing is visible, which is the point.

**The circuit breaker is on the runbook, not on the agent.** If two lanes in one slice both
report that a runbook step failed, stop dispatching, write the failure into the runbook as an
amendment, and ask the user before continuing. Two independent lanes hitting the same step is
not two bugs; it is the runbook being wrong, and every further lane you dispatch will hit it
too.

**The one thing that has no home anywhere else** is step 3's regression check. Every deploy
criterion in this phase asserts only its own slice's features, so "did S3 break S1" was a
question the pipeline could not answer — the AC pass rate is one number, and a number that moves
does not say which way or which test. The review compares this run against the previous one by
test name. Both files are already on disk; nothing new has to be run to get it.

**A finding that arrives mid-slice does not wait in someone's head.** Write it to
`plan/progress.yaml` `notes:` on the slice you are *in* — "S6 has no dependents, could come
before S4". `parity.py` already carries notes into its report and the slice review surfaces
them beside the reorder candidates, so an observation recorded at the moment it is real gets
acted on at the moment it is safe. That is also why `sequence.py` refuses to reorder while a
slice is in progress: the finding is welcome, the mid-flight reshuffle is not.
