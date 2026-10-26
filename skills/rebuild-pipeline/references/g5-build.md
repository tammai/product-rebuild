# G5 — Parallel spec & build, per slice

Goal: maximum safe fan-out, one slice at a time. Lane COUNT is an output of Gates 1 and
3, not a constant. Work happens in code repos; the workbench is read-only input
(submodule pinned to gate tags).

**The first time a code repo is created**, run the repo checklist in `g5-first-slice.md` (step 0 creates
it with `scaffold-repo`, then register it, give it a remote, confirm `pause-check` sees it, decide what the remote
is for, and write `.rebuild-workbench`). The repo is not set up until all six are done, and it is unguarded until
step 1 registers it. Read that file now if no code repo exists yet.

## Per-slice sequence

0. **Record this slice's AC flows against the legacy app — before any module starts.**
   Applies when the locked playbook says so: `playbooks/mobile-flutter.md` §15, i.e. a
   `client-only` mobile rebuild whose legacy app is still runnable. Other shapes and
   playbooks skip step 0 entirely; their AC suite is written with the code, as step 1 has
   always said.

   The precondition, checked before dispatching anything: every acceptance criterion in this
   slice has a Maestro flow under the workbench's `parity/flows/<feature-id>/`, and
   `maestro test parity/flows/<feature-id>` is **green against the legacy app**. If flows are
   missing or red there, recording them *is* this slice's first work — not a prerequisite
   somebody else clears.

   **Refuse to start the slice otherwise, and name the missing flows** rather than starting
   the modules and circling back. A flow written after the rebuild exists is a flow written
   against the rebuild: it asserts what was built, says nothing about the reference, and
   every later run agrees with the code by construction. That property cannot be recovered
   afterwards short of reinstalling the old app and re-recording — which is exactly the work
   that was skipped, now with a build in the way.

   Where a flow genuinely cannot be recorded — Maestro cannot drive that surface, or the
   legacy app no longer builds that screen — record *that*, per flow, in the flow file's
   header. It is then a normal test rather than a parity test and the slice proceeds. An
   unrecorded flow nobody declared is indistinguishable from one nobody wrote, which is how
   a parity suite quietly becomes a regression suite.

0a. **Record this slice's equivalence traces against the legacy system — before the backend
   lane starts.** Applies when `reference.kind: own-code` and the E4 preflight says the
   reference runs; every other project skips it and `parity.py` says the lane does not apply.
   This is step 0's `fullstack` branch: where a `client-only` mobile rebuild records Maestro
   flows against the old app, a rebuild that owns a backend records what the old **system**
   returned.

   For each feature in this slice, author the requests out of its UX flows and Rule Cards, then:

   ```sh
   python3 scripts/equiv.py record <feature-id>   # writes parity/equiv/<feature-id>/*.trace.yaml
   git add parity/equiv && git commit -m "equiv: record traces for <feature-id>"
   ```

   **The order is the whole property, exactly as it is for flows.** A trace recorded after the
   rebuild exists is derived from the rebuild: it asserts what was built, says nothing about the
   old system, and every later replay agrees with the code by construction. Unlike a flow, this
   one cannot be recovered at all once the legacy system is decommissioned — which on a
   replacement project is a scheduled event, not a hypothetical.

   Commit them before the lane starts. A committed trace is protected by the hook; an
   uncommitted one is still being recorded and stays editable.

0b. **Load the build runbook — S2 onward, before dispatching any lane.** Read
   `plan/BUILD_RUNBOOK.md` and pass it as a fixed input in every backend, frontend and infra
   brief (`subagent-briefs.md` part 2). It is not optional context: it is what S1 learned
   about this project's codegen, harness, reference quirks, fixtures and deploy
   prerequisites, and a lane that does not read it will rediscover all of it at full price.

   **A hook enforces this**, because an instruction the orchestrator applies to itself
   mid-slice is a budget and a hook is a limit — the same argument that made `gate-guard` a
   hook. `runbook_guard.py` blocks any write into a code repo while `plan/progress.yaml`
   shows a slice other than S1 `in-progress` and the runbook is absent. It finds the live
   workbench through the `.rebuild-workbench` marker at the repo root (step 5 of the repo
   checklist), and fails open when the marker is missing — so a repo created before this
   shipped is unguarded rather than broken.

1. **Specs + AC** — dispatch `spec-writer` per module in the slice, briefed per
   `subagent-briefs.md` — including part 6, the model `scripts/routing.py` resolved for this
   role, which is the worker tier (set `models.spec-writer` to `opus` in `.claude/model-routing.json` for a from-scratch module spanning many contracts). Spec inputs: the
   module's matrix features + flows + ground truth + contracts, **plus the module's Rule Cards** —
   a fixed input, not an optional one. Cut them per module: `python3 scripts/rules_for.py --features
   <the module's feature ids> --entities <the entities it writes> --out plan/rules-for/<Sn>-<module>.md`
   and pass that path. It gives the cards that name the module's features, and the `invariant` cards on
   entities it writes, in full, and every other card in the touched domains as one index line, so the
   writer sees every card's id and never the evidence of rules that are not its module's (the whole
   `findings/rules/<domain>.yaml` of every touched domain was the input before, and was paid for on
   every turn). Name the full `findings/rules/<domain>.yaml` paths in the brief too, for a card the index
   makes relevant. Specs are written to `plan/specs/<Sn>/<module>.md` in the workbench (they
   describe the product; code repos reach them through the submodule pin). Every spec ends
   with acceptance criteria: testable behaviors, each mapping 1:1 to a test at the lowest
   level that can observe it (see "Test depth and UI depth"). Where behavior is ambiguous, the RUNNING REFERENCE is the arbiter — check it,
   never guess. Run `python3 scripts/validate.py` when the spec-writers return and before you present them: it checks the
   `rule_id` join against lane R's cards, so a bad id surfaces now and not at a later check. Specs pass user
   review (propose-before-act) before any code.

   **Every acceptance criterion that implements a Rule Card carries `rule_id:`.** This is
   the join that makes lane R worth mining: without it the cards are a document nobody reads
   at the moment they are needed, which is precisely the state G1 mined them out of. It buys
   three things that did not exist before — `validate.py` reports the share of criteria in
   rule-bearing domains that cite no rule, `acsuite.py` and `parity.py` can say "12 of 14
   rules in `billing` are green" rather than only counting features, and a criterion that
   drifts from the reference has a locked, cited card to be wrong against.

   **An `invariant` card is cited from every module that writes its entities.** A module spec
   that writes any entity in an invariant's `entities[]` carries a criterion that performs the
   write and then asserts the property. One invariant is therefore cited from several slices,
   and that is the point: each new writer is a new way to break it. `validate.py` lists the
   invariants no criterion cites yet. That is advisory, because before the first slice that
   writes the entity it is expected.

   **Name the `rule_id` in the test too.** The AC→test mapping is 1:1, so the test that
   implements a criterion carries that criterion's rule id in its name (or its `classname`).
   That string is the only thing the JUnit output carries, and it is what the per-rule column
   groups on — a test that implements a rule but never names it is invisible to the rules
   table and reads there exactly like a rule with no test at all.

   **Where the card and your reading disagree, stop.** The card is gate-1 locked and carries
   `path` + `commit` + `line` into the reference's own source. A spec quietly specifying
   something else is the drift lane R exists to prevent, arriving by a different door.

   **Price the E2E criteria's prerequisites while writing them, not when running them.**
   For the smoke journey and the slice's one UI-level criterion, if it has one, name what has to exist for it to run at all — which operation
   creates the state it asserts on, which credential, which network path — and check each
   one is reachable through the locked contract. A criterion nobody can execute is
   indistinguishable from a passing one right up to the end of the slice, and by then the
   code is written: one project found its two hardest deploy ACs unrunnable *after* the
   whole slice was built and pushed, for two independent reasons, one of which was a Gate 4
   reopen. Both were answerable in a minute at spec time.
1b. **Lane plans — after spec approval, before any lane writes feature code.** The plugin's spec
   gate (`hooks/scripts/spec_gate_guard.py`) allows no edit over ~20 lines in a code repo until
   `PLAN.md` at the worktree root says `Status: approved`. It is a plugin hook, so it runs for
   every pipeline tool call whatever directory the session started in (see "The guards run for
   lanes" under Guardrails), and a lane with no plan is blocked on its first real edit. Your approval of the slice's specs is the approval the gate
   wants, and this step carries it there:

   - **One worktree and one branch per lane**, `slice/<Sn>-<lane>`, cut from the repo's main
     branch (`git -C <repo> worktree add -b slice/S3-billing-backend ../<repo>-S3-billing-backend`).
     The gate reads `PLAN.md` per worktree, so two lanes sharing a checkout would share a plan.
     On S1 the repo does not exist yet: run the repo checklist (`g5-first-slice.md`, step 0) first, then cut the
     worktrees.
   - **Write each lane's plan** with `python3 scripts/lane_plan.py <Sn> <lane> --worktree <path> --specs
     <the specs this lane builds>`. It writes the `PLAN.md` the spec gate reads: `Status:
     approved`, the lane's `Branch:`, an `Approved:` line (spec paths, workbench commit,
     approver), the specs verbatim, and one task row per acceptance criterion. It refuses specs
     with uncommitted changes, a worktree on the wrong branch, and an existing plan with
     unfinished rows. It records each plan in `plan/lane-plans/<Sn>.yaml`.
   - **Never let a lane write or approve its own plan.** `*.md` is exempt from the gate, so
     nothing mechanical stops it. That is why the plan comes from this script at the approval
     moment, and why `slice_review.py` re-hashes each plan's `## Spec` against what was
     recorded and names any lane whose approved spec changed underneath it.
   - **When a lane finds the spec wrong**, it sets `Status: amending`, which blocks its own
     non-trivial edits, and reports. That is the only `Status:` edit a lane may make, because it
     can only remove permission. Take it to the user. Once the corrected spec is approved and
     committed, run `python3 scripts/lane_plan.py <Sn> <lane> --worktree <path> --specs <...> --amend
     --reason "..."`. A row keeps its status only if its criterion text is unchanged, and the
     reason is logged under `## Amendments`.
   - **At slice end**, once every row is `Done` and the slice is deployed, `boundary.py <Sn>` (see "Between
     slices") archives each lane; by hand it is `python3 scripts/lane_plan.py archive <Sn> <lane>`. It moves `PLAN.md` to `plan/lane-plans/archive/` in the
     workbench, so the code repo's tree carries no plan after the slice (a plan left behind keeps
     its `Status: approved`, which the gate would honour for the next lane cut from that tree). It
     refuses a plan with unfinished rows, and it records an edited `## Spec` for the slice review
     to name.
2. **Backend** — one lane per bounded context touched (module or service per Gate 3).
   On the first slice this is where the repo checklist in `g5-first-slice.md` runs (`scaffold-repo`), and the lane
   starts from the generated skeleton and the locked contracts; on every slice after, the repo
   already exists and this step starts at codegen from `contracts/`.
3. **Frontend** — same: first slice creates the repo through `scaffold-repo` (`nuxt`
   or `next` per Gate 3), thereafter build against the generated typed client. May split
   per feature area.

   **For a `client-only` rebuild, this lane is the whole build** and lane 2 does not exist —
   there is no backend to write. It splits per feature module instead of per bounded context,
   still one agent per module, still against a **generated** client (from the frozen
   `contracts/openapi/`, committed, with CI regenerating and diffing it). The migration work
   the `on-device-migration` ADR decided is its own module in whichever slice first touches
   session or local data — never a task appended to a feature module, because it is the one
   piece of code that runs once per user with no undo.
4. **Infra** — CI/CD, environments, deploy. Migrations serialize through ONE queue
   regardless of lane count, and the queue is concrete:

   - **Assign migration numbers when the slice starts.** For each lane whose spec changes the
     schema, take the next free number (or a range) on the repo's main branch, in lane order,
     and write it into that lane's spec before you approve it, so it reaches `PLAN.md` verbatim.
     Put the same number in the lane's brief (the brief names the number; the migration rules are in `lane-worker`'s agent file). A lane
     never picks its own: in one slice three lanes each added a migration at the same time.
   - **No lane runs `up` on a shared stack from a tree missing a lower-numbered migration.** A
     migration tool that records only the highest applied version (most of them) silently skips
     a lower number applied after a higher one. In that slice one lane took the shared test stack
     to version 29, a later `up` from a tree that also had 28 skipped 28, and the schema
     disagreed with the code until a clean reset. Lanes test migrations on their own databases.
   - **The joint run starts with a clean `reset`** of the shared stack, after every lane's
     migrations are merged, so they apply once, in number order.
   - The runbook's `## Migration order` section records the tool's behavior and the reset
     command, so S2's lanes do not learn it the same way.
4b. **No verifier loop by default.** Through 1.0.0 every lane went through an implement/verify loop,
   capped at three rounds, before the joint run. It cost a fresh agent and a resumed lane per
   round, on diffs the joint run and the slice review look at anyway, and 1.1.0 removed it. A lane is
   done when it reports its rows `Done` and its own tests (per the test cadence) pass. The
   independent checks that remain are the joint run, which is the evidence bar, and
   `slice_review.py`, which names any lane whose approved `## Spec` changed.

   - **Dispatch every build lane as the `build-lane` role** (lanes 2–4 above), with the agent
     and model `scripts/routing.py --role build-lane` resolves (`lane-worker`). Pass both
     on the Agent call, together with the build-lane brief and its worktree. It is never
     `general-purpose`: the standing rules live in the agent file.
   - **An audit is the user's call, once.** If the user asks for one (a lane touching money or auth
     is the usual reason), dispatch one fresh `lane-verifier` for that lane with the brief in
     `subagent-briefs.md`, and show the user its JSON verdict. There is no automatic fix round,
     no re-verify and no cap: what to do with a `FAIL` is the user's decision. Nothing records it.
   - **A lane that finds the spec wrong** goes to the amend path in step 1b, as before.

   A code review is not run per lane either. Whether to review is the user's call at the slice
   boundary, with the whole slice's diff in front of them.
5. **The joint run — once, at the end of the build.** One lane, named when the slice starts,
   runs the cumulative suite: every unit and integration/API suite in every repo, then the
   E2E set against the deployment — the latest checkpoint's smoke journey plus each slice's
   one UI-level E2E (at most one per slice, so the set grows by one a slice at most). An
   earlier checkpoint's smoke journey retires when a later one supersedes it; the
   lower-level suites carry its criteria. Immediately before it starts:

   ```sh
   python3 scripts/lanes_check.py stamp          # from the workbench root
   ```

   JUnit goes straight to `parity/<local-date>-ac.xml`, where `<local-date>` is today on the
   machine's own calendar — the date `parity.py` and `slice_review.py` look it up by.

   - **Brief the joint-run lane to drive the run with `scripts/run_phases.py`**: the clean
     reset, the stamp, each suite, each redeploy, as phases of ONE `run_in_background` process
     (`lane-worker`'s agent file, "Long runs", has the layout). One joint-run lane stalled three
     times in a slice, 13 to 18 minutes each, because it ran each suite under `nohup` and
     watched a done-marker with a Monitor. The harness does not track a `nohup` process, so its
     exit woke nobody, and the Monitor expired before the 45-minute suites finished. A Monitor
     is never the only signal that a run ended.
   - **Green means no failures, no errors, no more than 10% skipped, and no skip for an unset
     environment variable.** One joint run reported 0 failures with 670 of 1209 tests skipped,
     because the integration database settings never reached the test processes. The lane
     reports skips by reason, and `parity.py` and `slice_review.py` mark a run outside these
     bounds NOT GREEN. A criterion skipped for an unset variable did not pass; fix the
     environment and run again rather than rerunning the skipped specs one by one.
6. **Rerun only the failures.** The lane that owns each failure re-runs exactly the failed
   specs — not another full run — after `python3 scripts/lanes_check.py stamp --rerun`, with JUnit
   to `parity/<local-date>-ac-rerun.xml`. Both reports count the pair the same way and label
   every pass on rerun as flaky, code-changed or unverified (`g6-parity.md` says what each one
   means). A criterion still not green is PENDING with a reason; a slice does not close on an
   unexplained PENDING.

## Test depth and UI depth: as little as proves the behavior

**Every acceptance criterion gets exactly one test, at the lowest level that can observe it** —
unit, then integration or API against the real module, and only then a browser or device
test. A rule such as "an expired invite returns E-410" is an API test; it does not need a
browser. Browser/device E2E is reserved for what only a running UI can show, and the budget
is fixed:

- **One smoke journey per checkpoint slice** (g3-slicing.md): the three-to-five-step path
  named in `done_means`, run against the deployment. That is the deploy criterion.
- **At most one more E2E per slice**, for the single criterion whose risk is in the UI
  itself (a drag, an upload, an auth redirect). More than that is a signal a lower-level
  test was skipped; push it down.
- **Slices that are not checkpoints** deploy and run the smoke journey of the last
  checkpoint, nothing new. The cumulative regression signal comes from the lower-level
  suites, which are cheap.

Specs say the level each criterion is tested at (`spec-writer`), and the one-to-one mapping
holds: fewer E2E tests means the criteria moved down a level, not that they lost a test.

**UI is functional until the product is usable.** Lanes build the screens a criterion needs
to reach and observe behavior — default components, real loading/empty/error states, no
bespoke styling, no animation, no pixel parity. Do not spend lane budget, or a review
round, on visual detail. Polish is its own pass (see g3-slicing.md): it starts once the first
checkpoint is verified or the functional slices are done, runs against the mined UX flows and
the reference's screens, and is the one place visual comparison tools (Maestro, screenshots)
earn their cost. A UI defect found in a functional slice goes to `notes:` unless it blocks
the criterion.

## Test cadence within a slice

A lane left to decide how often to run the slow suites runs all of them after every batch, and
an orchestrator left to decide re-runs them to be sure. In one rebuild that was a 45-minute
deploy suite and a 45–60 minute Go suite after every batch, each run also blocking the other
lane's shared stack; in another, about two thirds of all test runs happened in the
orchestrator's own context, which is the most expensive place in the project to run anything —
every turn there carries the whole session. So this is fixed, and it is not a per-project
setting:

| When | Who | Run | Don't run |
|---|---|---|---|
| During the build | the lane | lint, type-check, unit and fixture tests for touched files; integration tests for touched packages; the ONE E2E for the criterion being worked on, if it is a UI-level one (`--grep` / `-run`) | the E2E set; the full backend suite |
| End of build, once per slice | the lane named for it (step 5) | ONE joint full run, JUnit to `parity/<local-date>-ac.xml` | extra "clean" full runs |
| After the joint run | the lane that owns the failure (step 6) | ONLY the failed specs, JUnit to `parity/<local-date>-ac-rerun.xml` | another full run |
| Any time | the orchestrator | nothing — it reads the JUnit files and the lanes' reports. A failure to investigate goes to a lane or a fork, never into the main context | any test command |

- **Redeploys are batched.** A lane redeploys only when an E2E test needs the new build, and
  says so before and after.
- **The evidence bar does not move.** A criterion is PASS only if its test passed in the joint
  run or in its rerun, counted as `g6-parity.md` describes.
- **Not configurable.** No project setting brings back a full suite after every batch. A suite
  that genuinely needs more ("always run the migration tests in full") is named in the build
  runbook as a per-suite exception with its reason, and every other suite keeps this cadence.
- **Scope.** G5 slice builds. GP keeps its own full-suite requirements.

**Frequency is half the cost; the price of one run is the other half.** In one rebuild a full
`go test ./...` took 7–10 minutes because every integration test ran `initdb` and all 56
migrations before its first assertion — about 2s of setup around tests that take
milliseconds. Caching the migrated cluster and cloning it per test cut it to 4½ minutes with
isolation unchanged. That is why the runbook's `## Test fixtures` section records setup cost as
a measured number, and why a harness whose setup dominates is fixed before any rule here is
relaxed to compensate.

## Guardrails you enforce as orchestrator
- No code against interfaces absent from locked contracts (hook also blocks workbench
  edits — if an agent needs a contract change, that is a Gate 4 conversation).
- **The scaffold is not optional and not partially adoptable.** Every code repo is created by
  `scaffold-repo` and keeps what it installed. Deleting its git hooks or CI, rewriting its
  `CLAUDE.md` pointer into a rules brief, or swapping the scaffolded stack for a hand-rolled one is
  a Gate 3 conversation (it contradicts the locked stack ADR), not a lane-level decision.
- **The guards run for lanes, from the plugin.** Claude Code loads a repo's
  `.claude/settings.json` hooks only when the session started in that repo, and rebuild sessions
  start in the project's parent directory. So the guards are this plugin's own hooks, which load
  wherever a session starts: a bash guard (`--no-verify`, force push, moving the git hooks), the
  spec gate (no edit over ~20 lines without an approved `PLAN.md`), the injection gate and
  canary, and the commit gates (Conventional subject; a `fix:` ships a test). In the linear
  rebuild the equivalents were installed in every repo and inert for the whole build, because
  nothing loaded them; only the repos' git hooks ran. Each guard judges only a repo listed in the
  workbench's `repos.yaml` and ignores everything else. A block names its guard and why: it is
  the rule, so follow its message and never edit around it. A Bash command is judged only by the
  directory it names, which is why the build-lane brief has lanes start commands with
  `cd <worktree> &&`: a command that names none is not judged at all.
- CI per lane: lint, tests, security scan, license scan, AC-coverage (every AC has a test).
  The scaffold already wrote `.github/workflows/rebuild-verify.yml`, one job per package running
  the recorded commands — this pipeline's extra jobs (license scan, AC-coverage) are **added to
  that file**, not a second workflow written alongside it.
- Cross-lane shared changes go through one serialized review path.
- **You run no tests.** Not a suite, not "just to confirm" after a lane reports. Evidence is the
  JUnit the lane wrote and the report it sent; a failure worth investigating goes to that lane
  or to a fork. See "Test cadence within a slice".
- **Watch the long runs, because nothing else will.** While any build lane has a run longer than
  a few minutes open, start ONE background process from the workbench root with `run_in_background`:
  `python3 scripts/lanes_check.py watch --interval 600` (use `--interval 300` while the joint run is
  open, because its phases hand off to each other and each hand-off is a chance to stall). It checks on
  its own schedule and prints nothing while there is nothing to act on, so it costs your context
  nothing until it exits. It exits 2 with the evidence when a driver died mid-phase, or when no test
  process or driver is alive and nothing has changed for more than 10 minutes, naming the newest file
  anywhere and its age (per repo and worktree: the last commit, the dirty count, the live test
  processes, each `run_phases.py` run's phase and driver state, and the newest results file). It exits
  0 after 8 hours (`--max-minutes`), so a forgotten watcher ends itself. When it exits 2, if a lane still
  has work, send that lane the evidence verbatim (file, age, status, counts) and tell it to resume;
  tell the user in one line; then start the watch again. Stop it (TaskStop) once every lane has sent its
  final report. It replaces a session-scoped cron that ran the plain check every 10 or 5 minutes, which
  was a full orchestrator turn per fire (24 to 30 a slice) to read the words "nothing to act on". The
  failure this exists for is specific: a lane watching its run with a Monitor, which expires after at
  most 30 minutes, then sitting idle "waiting for the notification" — 2½ hours once, and several
  shorter gaps, noticed only when the user asked.
  The same check names any code repo whose `.rebuild-workbench` marker is missing or points
  elsewhere while a slice is in progress (`pause_check.py` does too): `runbook_guard.py` fails
  open without it, so a repo created before the marker step existed had the guard off silently.
- **"Deployed" for a client app means a build a real person can install** — an internal
  TestFlight or Play internal-track release, on a device that is not the build machine, with
  the version and build number recorded. Not "it runs in the simulator", and not "CI built an
  APK". A slice whose deploy criterion is satisfied by a simulator run has skipped the half of
  the curriculum that signing, provisioning, store processing and rollout actually teach —
  and every one of those fails for the first time on the day you need it to work.
- **The slice is not done until deployed** and its `done_means` demonstrably true —
  the deploy is half the curriculum. Confirm with the user before marking a slice done,
  and record it in `plan/progress.yaml`, never in the gate-locked `plan/slices.yaml` —
  see `g6-parity.md`. Use `deployed` rather than `done` when a `done_means` clause is
  knowingly unmet, so the status stays honest without switching off creep detection.
- **A verification script names only what it RAN.** Skip modes, partial runs and
  human-blocked steps must not print a banner covering criteria they skipped, and a
  criterion whose step could not execute is reported PENDING rather than silently omitted
  from the tally. This is the same failure as a vacuous test: the artifact a human reads
  afterwards is the banner, and one that overclaims is worse than no script.

## The first slice whose deploy criterion needs the OUTSIDE WORLD to reach in

Every deploy criterion up to then is outbound and `localhost` serves it. The first inbound one (a webhook
delivery, an OAuth redirect that must resolve, a CI runner posting a result) needs a public origin as
configuration, a tunnel for local verification, a provider-side registration path, and the right credential
shape. They are in `g5-first-slice.md`, section 2. Read it when you price that slice's E2E criteria at spec time.

## Between slices — the boundary is the only cheap place to change the plan

Five steps, in order, then return here for the next slice. Steps 2 and 3 are one call.

1. **Record the slice's outcome** in `plan/progress.yaml` — `slices:` *and* `features:`.
   Filling in only the first is the natural thing to do and it is the documented trap: every
   feature then falls through to `matrix/features.yaml`'s `status:`, which is gate-1 MINING
   output about the reference, and the two vocabularies share the words `covered`, `partial`
   and `missing` so nothing looks wrong.
2. **Run the boundary** — `python3 scripts/boundary.py <Sn>`, after step 1 because parity reads
   `plan/progress.yaml`. One call does what was four to six turns: archives each of the slice's lane plans
   (a plan that will not archive is named, not skipped), runs G6 parity (`g6-parity.md`), runs the slice
   review, and says whether the upstream re-mine is due (`g6-parity.md` step 3). It exits 2 when something
   needs you: an unarchived lane, a failed step, or a due re-mine.
3. **Read the slice review** it printed (`plan/slice-reviews/<Sn>.md`). Generated from what is on disk,
   never composed: does the whole product still run (cumulative AC suite, and what regressed
   since the last run), what shipped, where that puts us in the order, what is pressing on the
   plan. **Advisory** — it locks nothing and blocks nothing. Present it, and say what you think.
4. **Act on the plan now, or not at all until the next boundary.** Slice *order* is
   `python3 scripts/sequence.py reorder <Sn> --before <Sm> --reason "..."` — logged, cheap, and refused
   once the next slice starts. What is IN a slice is still a gate-2 reopen.
5. **Write the build runbook (S1 only), or amend it (every boundary after)** — template in `g5-first-slice.md`.

**After S1: write `plan/BUILD_RUNBOOK.md`**, and amend it at every boundary after. The sections and what goes
in each are in `g5-first-slice.md`, section 3. Write it from what the S1 lanes reported, not from memory.
