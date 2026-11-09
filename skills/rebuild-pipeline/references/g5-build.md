# G5 — Parallel build, per slice

Goal: maximum safe fan-out, one slice at a time. Lane COUNT is an output of Gates 1 and
3, not a constant. Work happens in code repos; the workbench is read-only input
(submodule pinned to gate tags). The slices, their criteria and their recorded tests are rspec's
(`docs/build-plan.md`, `docs/criteria.lock.json`, `docs/acceptance/`); nothing here writes a spec.
SKILL.md 4e is the slice loop in short; this file is the detail.

**The first time a code repo is created**, run the repo checklist in `g5-first-slice.md` (step 0 creates
it with `scaffold-repo`, then register it, give it a remote, confirm `pause-check` sees it, decide what the remote
is for, and write `.rebuild-workbench`). The repo is not set up until all six are done, and it is unguarded until
step 1 registers it. Read that file now if no code repo exists yet.

## Per-slice sequence

0. **Step 0: every criterion of the slice has a recorded test or rspec's reason.**
   `python3 scripts/lane_plan.py step0 <Sn>` names each criterion with neither a level 2 test in
   `docs/acceptance/` nor rspec's recorded reason for level 1 (`unrecordable`, `read-only reference`);
   run `rspec:verify --only <features>` for them and check again. `lane_plan.py` opens no lane of a slice
   that fails it. A test recorded against the reference before the build exists is what makes the suite
   a parity suite: one written after the rebuild agrees with whatever got built.

0a. **Record this slice's equivalence traces against the legacy system — before the backend
   lane starts.** Applies under posture `observe` or `own-code` when preflight says the reference
   runs locally; every other project skips it and `equiv.py status` says why. Where rspec's recorded
   tests check each criterion, a trace records what the old **system** returned for a whole request.

   For each feature in this slice, author the requests out of its criteria in `docs/features/`, then:

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
   brief (`subagent-briefs.md`). It is not optional context: it is what S1 learned
   about this project's codegen, harness, reference quirks, fixtures and deploy
   prerequisites, and a lane that does not read it will rediscover all of it at full price.

   **A hook enforces this**, because an instruction the orchestrator applies to itself
   mid-slice is a budget and a hook is a limit — the same argument that made `gate-guard` a
   hook. `runbook_guard.py` blocks any write into a code repo while `plan/progress.yaml`
   shows a slice other than S1 `in-progress` and the runbook is absent. It finds the live
   workbench through the `.rebuild-workbench` marker at the repo root (step 5 of the repo
   checklist), and fails open when the marker is missing — so a repo created before this
   shipped is unguarded rather than broken.

1. **Lanes from rspec's criteria** — propose the lanes as one approval: which features each lane builds, in
   which repo (one lane per bounded context touched, merged where two contexts live in one repo and are small),
   the packages each will add, and the contract questions the slice raises. At most `rebuild.yaml`
   `budgets.parallel_lanes` lanes are open per slice. Then, per lane:

   - **One worktree and one branch per lane**, `slice/<Sn>-<lane>`, cut from the repo's main branch
     (`git -C <repo> worktree add -b slice/S3-billing ../<repo>-S3-billing`). The lane name is lowercase
     letters, digits and dashes: it becomes part of the sdlc feature's name. The spec gate reads the approval
     per branch, so two lanes sharing a checkout would share one. On S1 the repo does not exist yet: run the
     repo checklist (`g5-first-slice.md`, step 0) first.
   - **Open the lane**: `python3 scripts/lane_plan.py <Sn> <lane> --worktree <path> --features <F-…,F-…>
     --approved-by "<who approved>" [--risk high]`. It writes the lane's sdlc feature at Build (ACs citing the
     criterion IDs, sdlc's spec-backed mode), with your approval in its Gate log, which is what the spec gate
     (`hooks/scripts/spec_gate_guard.py`) reads; copies the lane's open recorded tests into the worktree's
     `acceptance/` (each checked against the workbench manifest's sha256) and the lock to
     `.rebuild/criteria.lock.json`. Hidden tests never reach a lane. `--risk high` when the lane touches auth,
     payments, secrets, PII, a schema migration or a breaking change to a public API: sdlc's review table
     reads it. It commits nothing in the code repo.
   - **The lane fills in the how, never the what.** It writes each task's files, the Public Surface and the
     Test and Run cells, and never edits a criterion: `slice_review.py` re-hashes the ACs against what was
     recorded and names any lane whose criteria changed underneath it.
   - **When a lane finds a criterion wrong**, it asks with sdlc's `state.py question`, which blocks its part.
     `python3 scripts/lane_plan.py questions <Sn>` batches the slice's questions for `rspec:amend` (the user
     approves a change to an MVP criterion's `then`); after the re-verify, `lane_plan.py refresh <Sn> <lane>`
     re-copies the lock and tests, and the lane's `state.py questions` unblocks it.
   - **At slice end**, once sdlc has shipped every lane (`Status: done`), `boundary.py <Sn>` archives each lane
     (`lane_plan.py archive <Sn> <lane>` by hand): the lane's change and state files are copied to
     `plan/lane-plans/archive/` in the workbench. It refuses a lane sdlc has not shipped.

   **Price the E2E criteria's prerequisites at approval, not when running them.** For the smoke journey and
   the slice's one UI-level criterion, name what has to exist for it to run at all — which operation creates
   the state it asserts on, which credential, which network path — and check each is reachable through the
   locked contract. A criterion nobody can execute is indistinguishable from a passing one right up to the end
   of the slice.
2. **Backend** — one lane per bounded context touched (module or service per Gate 3).
   On the first slice this is where the repo checklist in `g5-first-slice.md` runs (`scaffold-repo`), and the lane
   starts from the generated skeleton and the locked contracts; on every slice after, the repo
   already exists and this step starts at codegen from the locked `docs/openapi.json`.
3. **Frontend** — same: first slice creates the repo through `scaffold-repo` (`nuxt`
   or `next` per Gate 3), thereafter build against the generated typed client. May split
   per feature area.

   **For a `client-only` rebuild, this lane is the whole build** and lane 2 does not exist —
   there is no backend to write. It splits per feature module instead of per bounded context,
   still one agent per module, still against a **generated** client (from the frozen
   `docs/openapi.json`, committed, with CI regenerating and diffing it). The migration work
   the `on-device-migration` ADR decided is its own module in whichever slice first touches
   session or local data — never a task appended to a feature module, because it is the one
   piece of code that runs once per user with no undo.
4. **Infra** — CI/CD, environments, deploy. Migrations serialize through ONE queue
   regardless of lane count, and the queue is concrete:

   - **Assign migration numbers when the slice starts.** For each lane whose spec changes the
     schema, take the next free number (or a range) on the repo's main branch, in lane order,
     and name it in the lane approval, so it is part of what was approved.
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
4b. **Build, then sdlc's Review, per lane.** A lane builds through sdlc's Build and reports; its review
   is sdlc's too, run by you, because sdlc's Review stops for the user and a lane cannot ask one.

   - **Dispatch every build lane as the `build-lane` role** (lanes 2–4 above), with the agent
     and model `scripts/routing.py --role build-lane` resolves (`lane-worker`). Pass both on the
     Agent call, together with the build-lane brief, its worktree and the sdlc folder `lane_plan.py`
     printed. It is never `general-purpose`: the standing rules live in the agent file. The lane
     fills in the how, records every criterion red with `verify.py red`, builds, runs `verify.py`
     once, commits and reports, still at Build. **The lane's report is its hand-back message**, not the
     task notification: a lane whose `verify.py` runs in the background is announced `completed` with
     "has not reported yet" each time it waits (three times in the Kutt rebuild). Start Review only on
     the report, and only once `verify.py` in it says PASS with a head and tree. **A lane that goes
     quiet may have finished without reporting**: when a lane has sent nothing for longer than its
     `verify.py` takes (10 to 15 minutes on Kutt), look at its branch (`git -C <worktree> log -1`) and
     ask it for its status by SendMessage. A Kutt lane committed its fixes and sent nothing for three
     hours; it answered "I am waiting on nothing" the moment it was asked.
   - **A lane runs on the sdlc that opened it.** `lane_plan.py` records the sdlc folder and version in
     `plan/lane-plans/<Sn>.yaml` and prints it; name that folder in the lane's brief and in your own
     Review and `ship.py` calls until the lane ships, even if sdlc is updated meanwhile (the old version
     stays in the plugin cache). sdlc 3.0 refuses a state file 2.x wrote until `/sdlc:upgrade` migrates
     it, so update sdlc between slices, never mid-slice.
   - **Then run sdlc's Review for that lane, as sdlc's orchestrator would.** Read only the
     `## Review (Stage …)` section of sdlc's `skills/orchestrator/references/flow.md` and follow it
     with the lane's worktree, change and state files: decide from sdlc's table (security on high
     risk or sensitive paths, code on a large diff, a public surface or L, UI on UI paths), dispatch
     each review once, fresh. **Give every reviewer the lane's approved spec paths** with the diff,
     and tell it that behaviour a spec states, including reference behaviour a spec flags and keeps,
     is not a bug; a finding against it is rated against the spec. Without them, reviewers report the
     reference's own behaviour as defects, and sorting that out was most of a Kutt review round. The
     code review on an M lane is the built-in `code-review` skill, as sdlc says. The dependency audit
     sdlc's security review asks for is, for Go, `go run golang.org/x/vuln/cmd/govulncheck@latest ./...`
     from the lane's worktree (it builds with the module's own Go; an installed `govulncheck` built
     with an older Go fails on every package); the others take the agent and model `scripts/routing.py --role lane-review` (code and
     security) or `--role lane-ui-review` resolves, which are sdlc's reviewers on opus. A high finding
     goes back to the same lane (resume it with the issue list), fixed test first, then the fixes are
     checked once more. sdlc's stops are your stops with the user: the review choice on high risk, a
     second round that still fails, a high finding the lane disputes. Nothing fires (a low-risk lane
     with a small diff and no public surface): no review, as sdlc says.
   - **Then ship the lane through sdlc**: `ship.py` from the lane's worktree. It reuses the passing
     `verify.py`, sets `Status: done` and stages the record with the code. On the lane's own branch it
     makes no new branch. Commit, and merge the lane into the repo's main branch the way the repo's
     remote decision says (`g5-first-slice.md`, step 4). sdlc's Learn step files a lesson in the repo's
     knowledge; the build runbook (between slices) is still where cross-lane lessons go.

   1.1.0 removed a per-lane implement/verify loop for cost; 2.0.0 brings a review back, because review
   is what sdlc owns and this pipeline now wraps it. Expect nearly every lane to get one: sdlc's code
   review fires whenever `## Public Surface` is not `- none`, and a module almost always exports
   something (the 2026-11-03 end-to-end lane, one function and one exception, fired it). On an M lane
   that review is the built-in `code-review` skill; on L, or for security or UI, an opus agent.
5. **The joint run — once, at the end of the build, started by you.** It writes the workbench
   (the stamp, `parity/`, the run folder), and lanes may not write the workbench (the reference
   guard denies it), so the orchestrator starts it; it is one background process, so no test
   output enters your context. It runs the cumulative suite: every unit and integration/API suite in every repo, then the
   E2E set against the deployment — the latest checkpoint's smoke journey plus each slice's
   one UI-level E2E (at most one per slice, so the set grows by one a slice at most). An
   earlier checkpoint's smoke journey retires when a later one supersedes it; the
   lower-level suites carry its criteria. Immediately before it starts:

   ```sh
   python3 scripts/lanes_check.py stamp          # from the workbench root
   ```

   JUnit goes straight to `parity/<local-date>-ac.xml`, where `<local-date>` is today on the
   machine's own calendar — the date `parity.py` and `slice_review.py` look it up by.

   - **Drive the run with `scripts/run_phases.py`**: write the clean reset, the stamp, each
     suite and each redeploy as phases in `parity/runs/<local-date>-joint/phases.txt` (settings
     the tests need on `NAME=value` lines, never an `export` inside one phase: each phase is its
     own shell), then start `python3 scripts/run_phases.py parity/runs/<local-date>-joint` from
     the workbench root with `run_in_background: true`. It writes `<phase>.log`, `<phase>.done`
     and `status.json` and stops at the first failure. Read only `status.json` and the JUnit;
     a failure to investigate goes to the lane that owns it. One joint-run lane stalled three
     times in a slice, 13 to 18 minutes each, because it ran each suite under `nohup` and
     watched a done-marker with a Monitor. The harness does not track a `nohup` process, so its
     exit woke nobody, and the Monitor expired before the 45-minute suites finished. A Monitor
     is never the only signal that a run ended.
   - **Green means no failures, no errors, no more than 10% skipped, and no skip for an unset
     environment variable.** One joint run reported 0 failures with 670 of 1209 tests skipped,
     because the integration database settings never reached the test processes. The lane
     reports skips by reason, and `parity.py` and `slice_review.py` mark a run outside these
     bounds NOT GREEN. A criterion skipped for an unset variable did not pass; fix the
     environment and run again rather than rerunning the skipped specs one by one. Skips are
     reported by reason.
6. **Rerun only the failures.** The lane that owns each failure fixes it in its worktree and
   reports; you then run `python3 scripts/lanes_check.py stamp --rerun` and exactly the failed
   specs — not another full run — as one `run_phases.py` process, with JUnit to
   `parity/<local-date>-ac-rerun.xml`. Both reports count the pair the same way and label
   every pass on rerun as flaky, code-changed or unverified (`g6-parity.md` says what each one
   means). A criterion still not green is PENDING with a reason; a slice does not close on an
   unexplained PENDING.

## Test depth and UI depth: as little as proves the behavior

**Every acceptance criterion gets exactly one test, at the lowest level that can observe it** —
unit, then integration or API against the real module, and only then a browser or device
test. A rule such as "an expired invite returns E-410" is an API test; it does not need a
browser. Browser/device E2E is reserved for what only a running UI can show, and the budget
is fixed:

- **One smoke journey per checkpoint slice**: the three-to-five-step path named in the
  slice's `Done when`, run against the deployment. That is the deploy criterion.
- **At most one more E2E per slice**, for the single criterion whose risk is in the UI
  itself (a drag, an upload, an auth redirect). More than that is a signal a lower-level
  test was skipped; push it down.
- **Slices that are not checkpoints** deploy and run the smoke journey of the last
  checkpoint, nothing new. The cumulative regression signal comes from the lower-level
  suites, which are cheap.

rspec's recorded tests are already at the level they observe; a lane's own tests follow the same rule, and
the one-to-one mapping holds: fewer E2E tests means the criteria moved down a level, not that they lost a test.

**UI is functional until the product is usable.** Lanes build the screens a criterion needs
to reach and observe behavior — default components, real loading/empty/error states, no
bespoke styling, no animation, no pixel parity. Do not spend lane budget, or a review
round, on visual detail. Polish is its own pass: it starts once the first checkpoint is
verified or the functional slices are done, runs against rspec's `screens.md` and the reference's screens, and is the one place visual comparison tools (Maestro, screenshots)
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
| End of build, once per slice | the orchestrator starts it as one background `run_phases.py` process (step 5) | ONE joint full run, JUnit to `parity/<local-date>-ac.xml` | extra "clean" full runs |
| After the joint run | the lane that owns the failure fixes it; the orchestrator starts the rerun (step 6) | ONLY the failed specs, JUnit to `parity/<local-date>-ac-rerun.xml` | another full run |
| Any time | the orchestrator | nothing in its own context beyond starting those two background runs — it reads `status.json`, the JUnit files and the lanes' reports. A failure to investigate goes to a lane or a fork, never into the main context | any test command in the foreground |

- **Redeploys are batched.** A lane redeploys only when an E2E test needs the new build, and
  says so before and after.
- **The evidence bar does not move.** A criterion is PASS only if its test passed in the joint
  run or in its rerun, counted as `g6-parity.md` describes.
- **sdlc's `verify.py` keeps this cadence by what the repo calls its test command.** It runs the
  repo's whole verify plan every time, including `commands.test` in `.sdlc/config.json`. In a rebuild
  repo that command is the **fast suite** (unit and fixture tests), which the scaffold records; the
  integration, E2E and deploy suites are not sdlc commands and run only at the joint run. Each
  criterion's own test still runs alone, through its Run cell. Never point `commands.test` at the full
  suite to "be sure": every lane would then run it at every `verify.py`.
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
- **The guards run for lanes, from both plugins.** Claude Code loads a repo's `.claude/settings.json`
  hooks only when the session started in that repo, and rebuild sessions start in the project's parent
  directory. So the guards are plugin hooks, which load wherever a session starts. This plugin's: the
  spec gate (no edit over ~20 lines without an approved lane), the injection gate and canary, and the
  commit gates (Conventional subject; a `fix:` ships a test). sdlc's (2.4 or later): its guardrails
  (force push to main, `reset --hard`, secrets, sensitive files and the rest, from each repo's
  `.claude/hookify/`) and its role guard, which reach a repo below the session's directory when that
  repo is set up for sdlc and the call names it. Each of this plugin's guards judges only a repo listed
  in the workbench's `repos.yaml` and ignores everything else. A block names its guard and why: it is
  the rule, so follow its message and never edit around it. A Bash command is judged only by the
  directory it names, which is why `lane-worker`'s agent file has lanes start commands with
  `cd <worktree> &&`: a command that names none is not judged at all. Your own shell is judged the same
  way: while its directory is inside a set-up repo, sdlc's guardrails read your commands' text too, so
  write documents with the file tools, never a heredoc that quotes a guarded command.
- CI per lane is sdlc's `.github/workflows/sdlc-verify.yml`, written by its setup from the repo's
  recorded commands, with nothing added: sdlc's verify already fails a criterion with no test, and this
  pipeline ships no license-scan job. Never write a second workflow alongside it.
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
- **The slice is not done until deployed** and its `Done when` demonstrably true —
  the deploy is half the curriculum. Confirm with the user before marking a slice done,
  and record it in `plan/progress.yaml`, never in the gate-locked `docs/build-plan.md` —
  see `g6-parity.md`. Use `deployed` rather than `done` when a `Done when` clause is
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
   Filling in only the first is the natural thing to do, and then every feature of the slice reads as
   `planned` in the coverage figures.
2. **Run the boundary** — `python3 scripts/boundary.py <Sn>`, after step 1 because parity reads
   `plan/progress.yaml`. It archives each of the slice's lanes (a lane that will not archive is named, not
   skipped) and runs G6 cheapest first (SKILL.md 4f): the open suite, the hidden suite, equivalence, coverage
   and the slice review, bug-hunter and the human sample. It also says whether the upstream re-mine is due.
   It exits 2 until the boundary passes.
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
