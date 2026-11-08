# Product Rebuild Playbook

**Purpose:** a repeatable process for rebuilding an existing product end-to-end as a way to learn the full product development lifecycle. The input is a reference product: typically OSS (an OpenProject, a Twenty CRM, a Webstudio), a well-understood category (CRM, project management, web builder), or **an app you already own and are replacing on a new stack** — a legacy React Native app rebuilt in Flutter is the same pipeline with three fields set differently at G0. The output is a completed, full-featured, production-ready codebase.

**Scope:** reference selection through a verified production-readiness gate. Out of scope: go-to-market, pricing, growth.

**Since 3.0** product-rebuild is an orchestrator over three plugins, and owns only what needs two of them at once:

| Plugin | Owns |
|---|---|
| **rspec** | the spec and its verification: discovery, the feature list, stories with criterion IDs, domain rules, ADRs, contracts, the audit, tests recorded against the running reference, the build plan |
| **sdlc** | the build: each lane is an sdlc feature in spec-backed mode, built, verified and reviewed by sdlc's own flow |
| **bug-hunter** | defect search at each slice boundary, with every finding reproduced and classified |
| **product-rebuild** | G0 (reference, posture, playbook, budgets), preflight, the gates and their locks, the hidden tests, the slice loop, G6, routing, GP |

Where each 2.x capability went is in [MIGRATION-3.md](MIGRATION-3.md).

**Design rules** (from the 3.0 spec set):

1. **Verification sits with the producer.** rspec verifies its spec, sdlc its tests, bug-hunter its findings. This pipeline adds only locking, hidden tests, parity and routing.
2. **The reference is the oracle.** Agreement between agents is never evidence. A check counts when it compares against the running reference, a recorded test or a cited source.
3. **Writer and checker never share a context.** Every judge, verifier and reviewer starts fresh.
4. **Cheap checks first, expensive checks gated.** A boundary stops at the first failure class that needs a fix.
5. **No silent pass.** A check that cannot run reports `not run: <reason>`, which no gate accepts as a pass.
6. **Human judgment is concentrated into five gates**, plus the decisions autopilot parks. Nothing downstream of a gate may contradict what it locked; changing a locked decision means formally reopening the gate.

---

## 1. Operating model

### 1.1 Pipeline at a glance

```
G0 Reference, posture, playbook, budgets; preflight
rspec init → discover → features           ── GATE 1: feature lock (features.md, domain.md, departures.yaml)
rspec stories → tech                        ── GATE 3: architecture lock (accepted ADRs; adr/ playbook + scaffold manifest)
rspec audit → verify → handoff              ── GATE 2: slice-plan lock (build-plan.md, ≤ 10 criteria a slice)
rspec check; holdout.py split               ── GATE 4: contract lock (openapi.json, schemas/, criteria lock, test bundle)
G5 per slice: step 0, sdlc lanes on rspec's criteria, spec questions → rspec:amend
G6 per slice: open suite → hidden suite → equivalence → coverage → bug-hunter → human sample; route.py
GP production readiness                     ── GATE 5: prod-ready lock (terminal)
```

Gate names keep their 2.x numbers so locks, tags and docs stay readable; their order follows rspec (architecture before slicing).

### 1.2 Humans vs. agents

| Work | Owner | Notes |
|---|---|---|
| Discovery, stories, ADR drafts, contracts, audit, recorded tests | rspec's agents | rspec runs its own fan-out and checks |
| Feature list approval, each ADR decision | Human, inside rspec | rspec stops for them |
| Lane builds | sdlc features, one `lane-worker` agent each | sdlc's Build, Review on sdlc's table |
| Defect search | bug-hunter | each draft reproduced by a fresh verifier |
| G6 sequencing, routing, coverage reports | Automated (`boundary.py`, `route.py`) | |
| The human sample at each boundary | Human | compares 2–3 features against the running reference |
| Departures (accepted differences) | Human | never decided by an agent |
| GP drills (restore, failover) | Human | performed, not described |
| All five gates | Human only | non-delegable |

Every agent row is a stretch the pipeline can run unattended — that is autopilot: the agent rows, chained, checkpointing to disk after each unit, parking what only a human may decide.

### 1.3 Artifact-first rule

Every phase boundary is a file with a contract (`contracts/v1/`: criteria, the criteria lock, the test bundle, departures, findings, cost lines), checked by a script. If a phase's output cannot be checked, the phase is not done.

---

## 2. G0 — Reference, posture, playbook, budgets

**Goal:** pick the reference and record what may read it *before* any agent does.

- **The reference.** Prefer OSS with an active repo, real deployments and a public changelog. Or your own product: `reference.kind: own-code`, `reference.upstream: frozen` — the running instance is the app you already have, and the frozen reference is a permanent arbiter for ambiguous behavior. Keep it runnable for the life of the project.
- **License posture** (`license-posture.md`): private learning allows reading any OSS source; intending closed distribution later means treating copyleft references clean-room. This playbook is process, not legal advice.
- **`reference.posture`** in `sources.yaml` (G0 shows the licence and asks; the legal fit is yours):

  | | strict | observe | own-code |
  |---|---|---|---|
  | Spec side reads reference code | no | yes (rspec OSS mode) | yes |
  | Spec side observes and records behaviour | yes | yes | yes |
  | Build lanes may read reference code | no | no | yes |
  | Equivalence (traffic replay) | no | yes, on a local reference | yes |

  Build lanes never read the hidden tests under any posture. `hooks/scripts/reference_guard.py` denies a lane's Read, Grep, Glob and Bash calls that name the reference checkout or the holdout. **It is a guard, not a sandbox**: a path computed at run time gets past it. Use `strict` for a sensitive reference.
- **Architecture playbook and target shape** (`sources.yaml` `architecture:`): the playbook supplies the stack and the scaffold manifest code repos are created from (`web-modular-monolith`, the org default; `mobile-flutter` for a Flutter client; a file you wrote; or `none`). `target_shape` is `fullstack` or `client-only` (the API exists and stays). Getting it wrong means specifying the wrong product.
- **Budgets** (`rebuild.yaml`, shown once): parallel lanes 3, recorders 4, hunters per slice 6, bug-hunter tokens per slice, fix rounds 2. The scripts that spend each one read it. Every orchestrated run writes a contracts C7 cost line (`cost.py add`, or bug-hunter's `--cost-log`), and the boundary prints the slice's cost by stage.
- **Preflight**, last: `python3 scripts/preflight.py` checks the checkout is at `pinned_commit` (every `[code]` citation in the spec is written against it), finds the build, probes the running instance, and writes `PREFLIGHT.md` with a verdict. **Not-ready holds rspec's discovery and nothing else.** Running the reference's own build and tests is opt-in (`--run-build --run-tests`): they are a third party's commands.
- **Off-machine from day one:** give the workbench a remote, private unless the posture allows distribution, and push gate tags after every lock (`git push && git push --tags`): code repos pin the workbench as a submodule at `gate-N/vN`.

**Exit:** reference chosen with rationale; `license-posture.md` (with prior attempts and off-limits, whose paths also go in `sources.yaml` `denied:`); `sources.yaml` reviewed; workbench pushed; `PREFLIGHT.md` Ready or Ready-with-gaps.

## 3. The spec: rspec's stages and Gates 1, 3, 2, 4

The skill runs each stage with rspec's own skill and reads rspec's `progress.py` for where it stands; it never does a stage's work. The workbench holds the spec in rspec's single-repo layout (`docs/`).

- **Gate 1** (after `rspec:features`, the user approves the list) locks `features.md`, `domain.md` and `departures.yaml`. The rebuild's rspec goal is always `production`.
- **Before `rspec:tech`**, `python3 scripts/playbook.py vendor` copies the playbook and its scaffold manifest to `adr/`, and its stack line becomes rspec's stack preference.
- **Gate 3** (after the ADR approval, rspec handoff step 1) locks `docs/decisions/` and `adr/`; it refuses an ADR still `Proposed` and a workbench with no valid scaffold manifest, so the stack every code repo is created from cannot change under the project.
- **Gate 2** (after `rspec:audit` and `rspec:verify`, and the build plan) locks `build-plan.md`: vertical slices, each shippable and testable on its own, at most about 10 criteria each.
- **Hidden tests** (`python3 scripts/holdout.py split`, after `rspec:check`): 25% of each slice's level 2 tests, at least one per feature with three or more criteria, drawn from a recorded seed, moved to a git repo `<project>-holdout/` beside the workbench that no code repo may contain. Lanes never see them; at G6 they are run per criterion and reported with the observed behaviour only, so a failure report does not leak the test.
- **Gate 4** locks `openapi.json`, `schemas/`, `criteria.lock.json` and `acceptance/manifest.json`, and records the holdout seed and list hash. Under `observe` or `own-code` it refuses while fewer than 90% of MVP criteria are at level 2 (a recorded test), unless the user signs a reason.

Slice *order* is a logged decision (`sequence.py reorder --reason`); what is *in* a slice is a gate-2 reopen.

## 4. G5 — the slice loop

1. **Step 0** (`lane_plan.py step0 <Sn>`): every criterion of the slice has a level 2 test or rspec's recorded reason; otherwise `rspec:verify --only <features>`.
2. **Lanes** (`lane_plan.py <Sn> <lane> --features …`): each an sdlc feature whose ACs cite criterion IDs, with its open tests and a lock copy in the code repo. Code repos come from `scaffold-repo`, never by hand.
3. **Spec questions**: a lane that finds a criterion wrong asks with sdlc's `state.py question`; the slice's questions are batched for `rspec:amend` (the user approves an MVP `then`), re-verified, and the lanes refreshed.
4. **Recorded tests are read-only**: a committed file under `docs/acceptance/` changes only after `flows.py unlock --acceptance --reason` — loosening an assertion to make a build pass is a logged human decision.

Detail: `skills/rebuild-pipeline/references/g5-build.md`, and `g5-first-slice.md` for the first repo, the first inbound integration and the build runbook.

## 5. G6 — each slice boundary, cheapest first

`python3 scripts/boundary.py <Sn>` runs, stopping at the first step that leaves a build-defect or spec-gap open:

1. **Open suite**: the lanes' JUnit; each failure re-run once (a pass on the re-run is flaky, not a finding).
2. **Hidden suite**: `holdout.py run`; 100% pass, or each failure explained by a departure.
3. **Equivalence**: recorded traffic replayed against the build, under `observe` or `own-code` with a local reference.
4. **Coverage and regression**: `parity.py` and `slice_review.py`, over rspec's feature list and build plan.
5. **bug-hunter**: `bug-hunter:hunt --oracle <spec> --target rebuild --reference reference --format finding-v1 …`, browser mode when the code repo has Playwright.
6. **Human sample**: 2–3 features drawn from a seed, weighted to criteria below level 2; a person compares them with the running reference and records `agree` or `differs`. Autopilot parks it.

`route.py <Sn>` sends each reproduced finding by class: build-defect and test-defect to an sdlc fix lane, spec-gap to `rspec:amend` then a fix lane, reference-defect to the user (copy it, or add a departure), flaky and environment to the orchestrator. A third fix round is the user's decision.

**One departures registry**: every accepted difference from the reference is an entry in `docs/departures.yaml` (contracts C5), read by every check and by bug-hunter; only a human decides one.

The boundary passes when both suites are green or explained, no high finding is open, bug-hunter has run and the sample is recorded. The upstream re-mine (every 30 days, while the reference ships) reruns rspec's coverage pass and triage; new features enter at a boundary, never mid-slice.

## 6. GP — production readiness and Gate 5

One checklist: rspec's `production-readiness.md`. GP adds execution: each NFR's stated verification is run against the production candidate with evidence (`gp.py nfr`, `gp.py check`); drills are performed by a named person. Gate 5 refuses on an unchecked item, missing NFR evidence, a hidden test that failed or did not run, an unexplained red equivalence trace, an open high finding, a `proposed` departure, or an MVP criterion below level 1. A client app shipped to devices adds the client checklist in `references/gp-production.md`.

## 7. Parallelization map

| Phase | Parallel across | Human |
|---|---|---|
| G0 | — | reference, posture, playbook, budgets |
| rspec stages | modules (rspec's cap), audit agents, recorders | feature list, each ADR, **Gates 1, 3, 2, 4** |
| G5 | lanes (budget, default 3) | lane approval, spec questions that change an MVP `then` |
| G6 | hunters (budget, default 6) | departures, the human sample |
| GP | checklist items | drills, **Gate 5** |

Serialization points, by design: the five gates, the migration queue, cross-lane shared changes, and the human drills in GP.

## 8. Upgrading a workbench

`rebuild_init.py` vendors the schemas and scripts into each workbench **at scaffold time**, on purpose — a workbench is a self-contained, versioned copy, and a project mid-slice is not improved by its tooling changing underneath it.

**A workbench made by an older major release is not upgraded.** 3.x orchestrates rspec, sdlc and bug-hunter; 2.x mined the reference itself, 1.x lanes worked under `PLAN.md`, and 0.x was a different plugin. There is no migration. `upgrade.py` refuses a workbench whose `locks/pipeline.yaml` does not say `rebuild_major: 3` and says to finish that rebuild on the release that made it (2.x: product-rebuild 2.2.0).

Within 3.x, dry run first (the default copies nothing), then apply:

```sh
python3 scripts/upgrade.py
python3 scripts/upgrade.py --apply
```

It classifies every vendored file against `locks/tooling.json`, the provenance manifest written at scaffold time:

| State | Meaning | `--apply` |
| --- | --- | --- |
| `new` | the plugin has it, this workbench does not | copies |
| `stale` | pristine vendored copy, plugin has moved on | copies |
| `modified` | differs from the plugin **and** from its recorded hash — someone edited it here | **refuses** |
| `unknown` | differs from the plugin, no recorded hash to compare | **refuses** |
| `kept` | a local version a human chose to hold, on the record | never copies |
| `held` | safe to copy, but its script/schema pair is refused | waits for the pair |
| `current` | identical to the plugin | nothing |

**It runs itself.** At the start of every pipeline session the skill runs the plugin's copy with `--auto`: only `new` and `stale` files, only when no slice is in progress, no autopilot run is engaged and the tree is clean, as one commit, followed by `validate`. A refused file stays refused until you settle it: port your change onto the plugin's version, take the plugin's with `--apply --force <path>`, or hold yours with `--keep <path>` (`--diff <path>` first). `--apply` does not commit; `--auto` does.

## 9. Failure modes to watch

- **Doing a stage's work by hand** — writing stories, criteria, ADRs or tests outside rspec skips its checks. Run the stage.
- **A test written after the build** — it asserts what was built and says nothing about the reference. Step 0 holds a slice until its criteria have recorded tests or a reason.
- **Leaking the hidden tests** — a lane brief that names the holdout, or a failure report that quotes a test. The guard denies the path and reports carry only the criterion and the observed behaviour.
- **A difference accepted in one place and not another** — one registry, `departures.yaml`, read by every check.
- **Undocumented divergence from the playbook** — the playbook is vendored and locked at Gate 3; an ADR diverges with a reason or it adopts the default.
- **Horizontal slicing** — "all backend first" delays every lifecycle lesson to the end; rspec's slices are vertical and each ends deployed.
- **Agreement mistaken for evidence** — a lane's tests agreeing with its code. The hidden suite, equivalence, bug-hunter against the reference and the human sample are the checks that compare with the reference.
- **Skipping GP** — declaring victory at feature parity. The definition of done *is* Gate 5, and its items require evidence produced by doing.
- **Chasing upstream mid-slice** — upstream changes enter only at slice boundaries.
