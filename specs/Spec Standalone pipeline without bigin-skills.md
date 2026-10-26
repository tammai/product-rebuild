# Spec: Standalone pipeline without bigin-skills

2026-10-26 · @Tam Mai · draft for sign-off

## Problem

`bigin-skills` is being retired. This pipeline depends on it in five places, and all five break the day it goes:

| Dependency | Where it lives | What breaks |
|---|---|---|
| **Repo creation.** Every code repo is made by `bigin-skills:bigin-harness-setup`, never by hand. | `SKILL.md` baseline paragraph, `g5-build.md` step 0, `g0-reference.md`, both playbooks' `scaffold-profile:` | G5 has no way to create a repo. The `generic` fallback is defined as "bigin-harness-setup over a non-empty repo", so it goes too. |
| **The harness's Claude Code guards** (bash, spec gate, injection scan/gate, canary, bugfix-test, commit-msg). | `hooks/scripts/repo-hooks.mjs` forwards each repo's `.claude/settings.json` hooks | New repos register nothing, so the forwarder forwards nothing. **The guards go silently inert**, which is the failure 0.29.0 was written to remove. |
| **Build-lane and verifier agents.** | `bigin-skills:worker`, `worker-frontier`, `verifier`, resolved by `routing.mjs`; `g5-build.md` step 4b | Lane dispatch names agents that no longer exist. |
| **The model ladder**, copied from `model-router` v1.105.0. | `routing.mjs` (`PROFILES`, `BIGIN_AGENTS`, `PROFILE_EFFORTS`) and its header | Not a break, but the comment says the source of truth is a file in a plugin that no longer exists. |
| **The repo-level conventions**: `CLAUDE.md`, path-scoped `.claude/rules/`, commit-time hooks, CI. | Written by the harness into each code repo | A repo created without it has none of them. |

Two further couplings are conceptual, not mechanical. The `PLAN.md` format is "task-workflow's format", and `g5-build.md` step 4b is "`task-workflow`'s implement/verify loop". Both keep working as designs once their owner is named as this plugin, but both are described by pointing at a plugin that is going away.

**Licence is not a blocker.** `bigin-skills`, `sdlc` and this plugin are all MIT, and all the same author's, so porting needs no relicensing. The CHANGELOG's old "bigin-skills is PolyForm-Strict, this plugin is MIT" note is deleted, and `NOTICE.md` records only where ported code came from.

**What exists to port from.** `tammai/sdlc` (MIT, same author) already solves most of this in a form this pipeline can take: `setting-up-projects` is an interview-then-propose greenfield flow that generates with each ecosystem's official tool and records the project's own commands; `templates/project/` holds rules, guard rules and CI; `agents/verifier.md` is a fresh-instance verifier. The guards are the exception: `sdlc` expresses its guards as hookify rules, and the pipeline needs the hardened bigin guard code (sized diffs, gate-file asks, worktree resolution) that has run in real rebuilds. Those come from `bigin-harness-setup`'s `references/hook-guard.md`.

## Decisions made in the interview (2026-10-26)

| Question | Decision |
|---|---|
| Why | `bigin-skills` is being retired. |
| Version | **This is the breaking change: it ships as 1.0.0.** 0.x keeps working as it does today and is **not** upgraded to 1.x. |
| Name and repo | **A new plugin, `product-rebuild`, in a new repo, `tammai/product-rebuild`**, seeded from this repo's history. `tammai/product-rebuild-skills` stays the 0.x line, untouched, so no existing install can move to 1.x. |
| Existing rebuilds | **Clean break.** In-flight rebuilds finish on 0.x. No compat code, no detection of bigin-created repos, and 1.x never operates on a 0.x workbench (E23). |
| Scaffold depth | **Minimal skeleton plus templates**, not a feature-for-feature port of the Go and Nuxt scaffolds. The first slice's lane builds the first real module (E19). |
| Org conventions | Live in **playbook content** (stack, lint, CI, layout). The pipeline has no org-specific knowledge. |
| Relationship to `sdlc` | **Port into this repo** with attribution. No runtime dependency on `sdlc` either. |
| Guards | **This plugin's own hooks**, not written into each repo. `repo-hooks.mjs` is deleted. |
| Guards kept | Bash guard · spec gate (`PLAN.md`) · injection scan, gate and canary · commit gates. |
| Scaffold interview | **Confirm and fill gaps only.** G3/G4a already locked the stack. |
| Dropped outright | The `generic` fallback · every version gate (1.68.0, 1.105.0), the G0 install check and the marketplace instructions · the copied ladder · the per-repo harness overlay. |
| Per-repo `CLAUDE.md` | A **thin pointer**: the five commands and where the workbench is. Not a rules brief. |
| Models | Keep `routing.mjs` with **its own profiles**. Lane worker and verifier become ordinary roles. |
| Delivery | This spec, sign-off, then three build phases on a `v1` branch of `tammai/product-rebuild` that ship together as 1.0.0 (Phasing). |
| Licence | Everything is MIT. No relicensing question. |

## Goals and non-goals

**Goals**

- Nothing in the plugin, its docs, its playbooks or its evals names `bigin-skills`, `bigin-harness-setup`, or any `bigin-skills:` agent, outside the CHANGELOG and the historical specs.
- A repo created at G5 passes its own five commands on day one, from the locked playbook and a short, gaps-only interview.
- Every guard that ran for lanes in 0.33.0 and is on the keep list still runs, **from the plugin**, for every pipeline tool call that touches a listed repo, whatever directory the session started in.
- No guard is turned off by the migration without that being a recorded decision. The dropped ones (context-budget gate, session resume, precompact snapshot) are named in the CHANGELOG.
- A playbook that cannot scaffold is a Gate 3 failure, not a G5 surprise.

**Non-goals**

- Compatibility with bigin-created repos or `repos.yaml` entries that rely on them. Clean break.
- Reproducing `go-scaffold`, `nuxt-scaffold`, `nodejs-scaffold` or `next-scaffold` feature for feature (decided; see E19).
- Any change to 0.x beyond the fence in E23. 0.x keeps requiring `bigin-skills`, and when that goes away it is not this project's concern.
- Adopting `sdlc` as a dependency, or its orchestrator, S/M/L sizing, stages, knowledge folder or constitution. Only the setup flow, templates and the verifier's rules are ported.
- A Cursor mirror. `bigin-harness-setup` had one; no pipeline user has asked for it, and it halves the guard code (the `hook-io.mjs` host adapter is not ported).
- Changing G0 to G4 or the lane brief beyond the names of agents and the scaffold step.
- Changing where sessions start. They start in the project's parent directory, as today.

**Success metrics**

| Metric | 0.33.0 | Target |
|---|---|---|
| Mentions of `bigin-skills` / `bigin-harness` outside CHANGELOG and `specs/` | 73 lines across 13 files | 0, enforced by `eval/no-bigin.mjs` |
| Claude-side guards on the keep list that run for a lane's tool call | all, via forwarding | all, native |
| Guards that run **twice** for a tool call | 0 | 0 |
| New repos whose five commands pass on day one | depends on bigin version | 100% for both shipped playbooks, by `scaffold.mjs run-commands` |
| Questions the scaffold interview asks that the locked ADRs already answer | n/a | 0 |
| Plugins the pipeline needs installed besides itself | 1 | 0 |

## E19 — Scaffold a code repo from the locked playbook

**A second skill, `skills/scaffold-repo/`**, invoked by the orchestrator at G5 step 0, from an empty directory. It is the procedure; `scripts/scaffold.mjs` keeps the records exact. The split is `sdlc`'s and is kept: the skill makes judgment calls, the script does bookkeeping, and nobody hand-edits the lock.

**The playbook carries the scaffold, not a profile name.** `scaffold-profile:` (a pointer into another plugin) is replaced by a `scaffold:` block in the playbook frontmatter:

```yaml
scaffold:
  packages:
    - name: api
      path: apps/api
      generator: "go mod init {{module}} && ..."
      commands: { install: "go mod download", build: "go build ./...", lint: "golangci-lint run",
                  typecheck: null, test: "go test ./..." }
      templates: [go/Makefile, go/golangci.yml]
    - name: web
      path: apps/web
      generator: "npx nuxi@latest init {{path}}"
      commands: { ... }
  ask: [module, org]            # the only values the playbook cannot know
  ci: { os: [ubuntu-latest] }
```

`playbook.mjs` parses and validates it. A playbook with no `scaffold:` block, or `scaffold: none`, is flagged at G4a and blocks Gate 3, not G5. That is the fix for what the `generic` fallback was papering over: "an empty directory plus an unsupported stack is an unsatisfiable pair of rules". Under this design it cannot happen at G5, because Gate 3 refuses the playbook first.

**The interview confirms; it does not decide.** From `adr/playbook.md`'s `scaffold:` block and the locked stack ADRs, the skill builds a proposal and asks only the values the playbook lists under `ask:` plus whatever a generator needs that no ADR holds (package manager, module path, CI target). A question whose answer is in a locked ADR is a bug. Each question carries a suggested answer. **The user approves the proposal before anything is generated**, as in `sdlc`'s `stack` hard stop. Autopilot treats that approval as a halt, like spec approval.

**How much a scaffold builds: a skeleton, not a feature-for-feature port.** `go-scaffold` and `nuxt-scaffold` produced more than a skeleton: a modular-monolith layout, `oapi-codegen` wiring, CI templates. This follows `sdlc`'s rule instead: "a skeleton whose commands pass on day one, nothing for later". The generator output, strict typing, the test runner, a linter and one smoke test per package, plus templates for lint, CI and the module directories the playbook's own sections specify. The first real module is built by the first slice's lane, under a spec you approved. That moves who owns the layout from "a scaffold" to "a lane under an approved spec". It is a behaviour change from 0.x, and the 1.0.0 CHANGELOG says so, with the 0.x scaffold's extras listed so a playbook author can add any of them back as templates.

**Steps, in order, each recorded in `.rebuild/scaffold.lock.json` so an interrupted run resumes** (`sdlc`'s `step-done`):

1. `propose`: the interview above. Hard stop.
2. `skeleton`: run each package's `generator` (the ecosystem's own tool), then apply only strict typing, the test runner, a linter, and one passing smoke test per package. Pin the toolchain. Nothing for "later": no auth, database, Docker or infra the ADRs do not name for the first slice.
3. `commands`: write the five commands per package into `.rebuild/commands.json`; `scaffold.mjs contract` checks that every package has all five or an explicit `null`.
4. `run-commands`: install, then the verify plan in each package's directory, every exit recorded. All must exit 0. A failure is fixed in the skeleton, never in the command.
5. `rules`: render the path-scoped `.claude/rules/` from the playbook's templates. These are the repo-conventions half of the old overlay, now playbook-owned. Open question 2 on how many.
6. `git-hooks`: `scripts/pre-commit.sh` (runs lint, typecheck and the fast tests from the recorded commands) and `scripts/commit-msg.mjs` (a vendored copy of `lib/commit-rules.mjs`, E21), installed into `.git/hooks/` by symlink, or by a one-line shim on Windows where `ln -sf` fails or `uname -s` starts `MINGW|MSYS|CYGWIN`.
7. `ci`: render the workflow from the recorded commands, one toolchain setup per stack, install and verify per package, OS matrix from `ci.os`. A stack with no known setup action gets a `# TODO` line and a note to the user.
8. `claude-md`: the thin pointer, below.
9. `finalize`: commit per step (`chore(scaffold): <step>`), then add the workbench submodule as today.

**The thin `CLAUDE.md`.** Written once, user-owned afterwards, and short enough to read in one glance:

```
# <repo>
Rebuild code repo. Decisions and specs live in the workbench: <relative path>.
Commands (run from each package's path): install · build · lint · typecheck · test — see .rebuild/commands.json.
Guards run from the product-rebuild-skills plugin; a block names the guard. Do not edit around one.
```

It replaces the harness `CLAUDE.md`, whose line "Non-trivial features: /task-workflow" the lane brief had to override verbatim in E17b. That override paragraph is deleted from the brief, because nothing contradicts it now.

**File ownership, kept from `sdlc`**:

| Class | Examples | Rule |
|---|---|---|
| Generated | `.claude/rules/rebuild-*.md` | `scaffold.mjs render` overwrites freely |
| Seeded | `scripts/pre-commit.sh`, `.github/workflows/rebuild-verify.yml` | rewritten only if the lock hash matches; otherwise refused with a diff |
| Vendored | `scripts/commit-msg.mjs` | copied from the plugin, hashed in the lock, same refuse-if-modified rule as `upgrade.mjs` uses for workbench scripts |
| User-owned | `CLAUDE.md`, any other `.claude/rules/*.md`, all source | written once with approval; never touched after |

Plugin-owned files are named `rebuild-*`; everything else belongs to the project.

**Changes**

- `skills/scaffold-repo/SKILL.md`, `references/` (propose, skeleton, commands, ci), `templates/` ported from `sdlc` with attribution (E21), and `scripts/scaffold.mjs`: `status`, `propose`, `step-done`, `render`, `contract`, `run-commands`, `status --drift`. It carries a header comment per the repo convention. Node only, CRLF-safe reads, no Python.
- `scripts/playbook.mjs`: parse and validate `scaffold:`; remove `scaffoldProfile`. G4a and Gate 3 report a missing or `none` block.
- `references/playbooks/web-modular-monolith.md`, `mobile-flutter.md`: frontmatter `scaffold:` block; delete the "see `bigin-skills`" paragraphs and the §17 checklist line "Repo created through `bigin-skills`' `bigin-harness-setup`". The Flutter playbook's two lint commands (`custom_lint` for `riverpod_lint`, `import_lint` for the boundaries; they are separate tools) move into its `commands` so the day-one run cannot skip either.
- `references/playbooks/README.md`: the `scaffold` column and the "Writing your own" frontmatter example.
- `references/g5-build.md` step 0: rewritten to call the skill. The whole "fallback" and "version" text goes.
- `references/g0-reference.md`: the "Confirm the `bigin-skills` plugin is installed" bullet is deleted. G0 has nothing to install-check.
- `SKILL.md`: the baseline-dependency paragraph is replaced by one saying what G5 step 0 does and that the plugin needs nothing else installed.
- `README.md`: Install section loses the second plugin.

## E20 — Lane worker and verifier are this plugin's agents

**Two agent files**, `agents/lane-worker.md` and `agents/lane-verifier.md`, alongside `miner.md` and the rest.

- **`lane-worker`**: the build-lane brief's rules as an agent, so they stop being re-pasted into every dispatch. Its body carries what a worker must not do (edit `Status:`, `Branch:`, `Approved:` or `## Spec` in `PLAN.md`; run `up` on a shared stack from a tree missing a lower migration; start any workflow of its own) and its own context budget. Its `effort` is `high`. It is **not** a port of `bigin-skills:worker`, whose prompt was written for `task-workflow`'s step 4.
- **`lane-verifier`**: ported from `sdlc`'s `verifier` and cut to this pipeline's loop. A new instance every round, never resumed, never shown the lane's summary. It runs the build, lint, type-check and **full** test suite fresh (no filtered runs for the verdict), proves each `PLAN.md` task row's acceptance criterion with evidence, never edits source or tests, and returns one JSON verdict (`PASS|FAIL`, issues) for `lane-plan.mjs record-verify`. Its `effort` is `high`. A false PASS voids the only independent check between approved criteria and code, which is why it never runs below the verifier tier.

**The implement/verify loop is the pipeline's own.** `g5-build.md` step 4b keeps its shape (orchestrator dispatches, fresh verifier per round, resume the same lane with issues verbatim on `FAIL`, cap of 3, third `FAIL` is a halt, a wrong plan goes to the amend path). It stops being described as `task-workflow`'s step 4, and "step 5, the offer to run `/code-review`" is no longer a deliberate omission to explain. `lane-plan.mjs record-verify` is unchanged.

**The `PLAN.md` format stays**, field for field, because the spec gate (E21) reads `Status:` and `Branch:` and `slice-review.mjs` re-hashes `## Spec`. Only the header comments change: "task-workflow's format" becomes "this pipeline's format; the spec gate reads `^Status:\s*(\S+)` and `^Branch:\s*(\S+)`".

**Routing keeps its script and loses its source.**

- `PROFILES` stays `balanced` and `frontier` over three tiers, but is defined here with its rationale beside each rung. No "mirrors" comment, no version, no "copied, not imported", because there is nothing to drift from.
- `BIGIN_AGENTS`, the `external` field on `build-lane` and `lane-verifier`, and the "effort follows the profile for bigin roles" branch are deleted. `build-lane` and `lane-verifier` become ordinary roles in `ROLE_TIERS` with `why:` per role, resolving to `lane-worker` and `lane-verifier`.
- **Effort stays pinned in the agent file for all six roles.** The reasoning in the header ("effort cannot be passed at spawn time… a profile moves the model and leaves effort where each role's own reasoning put it") now covers lanes too. Where `frontier` puts the worker tier at `medium` and `lane-worker` is pinned `high`, that is the same expected, warned disagreement the miner already has. A project that wants the cheaper effort overrides the model and accepts the pin.
- `--role` output keeps printing `agent`; it now names this plugin's agents.
- The defaults stay as they are (`balanced`, sonnet workers). That is a deliberate no-change: this spec is not the place to re-open model choice.

**Changes**

- `agents/lane-worker.md`, `agents/lane-verifier.md`, new. Frontmatter carries a fallback `model:` pin as the others do.
- `scripts/routing.mjs`: as above. `PIN_FALLBACK` gains both roles. Header rewritten.
- `references/subagent-briefs.md`: the build-lane brief shrinks to what is per-dispatch (lane, worktree, specs, migration number); the standing rules live in the agent. The verifier brief becomes "plan path, diff range, no lane summary". Both stop saying "a `bigin-skills` agent, never `general-purpose`", but **keep the rule's substance**: a lane is dispatched as `lane-worker` and a verifier as `lane-verifier`, never as `general-purpose` with a hand-written prompt, because the standing rules live in the agent file and a stand-in prompt silently drops them.
- `references/g5-build.md` steps 1b and 4b: agent names.
- `eval/lane-plan.mjs`: the two assertions that name `bigin-skills:worker` and `bigin-skills:verifier` now assert this plugin's agents.

## E21 — The guards run from this plugin

**Why plugin hooks and not repo files.** Plugin hooks load wherever a session starts; a repo's `.claude/settings.json` does not (2026-10-06 test, recorded in `repo-hooks.mjs`). Writing guards into each repo, as `sdlc` does with hookify, would put them back where the forwarder had to rescue them. Putting them in the plugin removes both the forwarder and the double-run risk.

**Scope: only repos the pipeline owns.** A plugin hook fires in every session where the plugin is enabled, so each guard resolves the target's repo and checks that it is listed in `repos.yaml` of a workbench at or directly under the session root (a lane's worktree counts through its main repo). Anything else fails open, exit 0, naming the condition in the comment. This is `repo-hooks.mjs`'s existing scoping, kept.

**Target resolution is kept from `repo-hooks.mjs`** and moved into `lib.mjs`: file tools by `file_path`, `notebook_path` or `path`; `Bash` by a leading `cd <dir> &&|;` or a `git -C <dir>`; the nearest existing directory for a file in a new subtree; Windows `C:/` and MSYS `/c/` spellings resolving to the same repo (`nativePath`); a worktree reading its own `PLAN.md` and branch, never the session's. A `Bash` call that names no directory runs no repo guards. That is a gap this does not close, and the lane brief keeps its rule of starting every repo command with `cd <worktree> &&`.

**The guards kept, ported from `references/hook-guard.md`:**

| Guard | Event and matcher | What it does |
|---|---|---|
| `bash-guard.mjs` | PreToolUse `Bash` | Blocks gate bypass: `--no-verify`, `-n`, force push. |
| `spec-gate-guard.mjs` | PreToolUse `Write\|Edit\|MultiEdit\|NotebookEdit` | Blocks a non-trivial edit until the worktree's `PLAN.md` says `Status: approved` and its `Branch:` matches. Keeps the four hardening rules: a whole-file `Write` is sized by the lines it changes, not the length difference; path rules judge the real repo-relative path in the file's own worktree; an edit to the gates themselves asks whatever its size; `NotebookEdit` is sized from `new_source`. Tests, docs and `*.md` stay exempt, as before. |
| `injection-scan-guard.mjs` | PostToolUse `WebFetch\|Bash\|mcp__.*` | Stage 1: flags fetched content that reads as an instruction. |
| `injection-gate-guard.mjs` | PreToolUse `Bash\|Write\|Edit\|WebFetch\|mcp__.*` | Stage 2: asks before the next risky call after a flag; stage 3 denies any call whose input carries the canary. |
| `canary-seed.mjs` | `SessionStart` | Seeds a per-session canary token. **This works here and could not under the forwarder**: the old spec refused to forward `SessionStart` because a pipeline session spans several repos, and running one repo's seed for it was wrong five ways. A plugin hook is the session's own, so one seed per session is simply correct. It seeds only when a workbench is at or under the session root. |
| `commit-gates.mjs` | PreToolUse `Bash` | Conventional-Commit subject on `git commit -m`; a `fix:` commit needs a staged regression test (`bugfix-test`'s rule). |

**What is deliberately not ported:** the context-budget gate, `session-resume-check`, `precompact-snapshot` and `install-hooks`' `Setup` bootstrap (the `.git/hooks/` clone problem is open question 3), the `vendored-contract-guard` (a polyrepo rule for repos with a vendored spec; the pipeline's contracts live in the workbench), the instructions trace (opt-in in bigin already), and the Cursor host adapter.

**Commit rules are written once.** `lib/commit-rules.mjs` holds the subject pattern and the `fix:` detection. `commit-gates.mjs` imports it for the Claude-side check, and E19 step 6 vendors a copy into each repo as `scripts/commit-msg.mjs`, so the git hook catches commits made outside Claude and the two cannot drift: one source, one hash recorded in the lock.

**Results combine strictest-first**, block over ask over allow, as `repo-hooks.mjs` does for forwarded hooks. A guard that throws is a block with its stderr, not a pass. A guard that silently stopped running is the failure this whole file exists to prevent.

**Provenance.** The guard code comes from `bigin-skills` and the setup flow, templates and verifier rules from `sdlc`; both are MIT, so `NOTICE.md` names each source and its path, and `licenses/` holds the licence texts, following `sdlc`'s own layout. No relicensing is involved.

**Changes**

- `hooks/hooks.json`: register the six guards on their events; **remove the two `repo-hooks.mjs` registrations** and the `SessionStart` entry is added.
- `hooks/scripts/`: `bash-guard.mjs`, `spec-gate-guard.mjs`, `injection-scan-guard.mjs`, `injection-gate-guard.mjs`, `canary-seed.mjs`, `commit-gates.mjs`, new. Each opens with the header comment the repo requires: what it does, why it is a hook and not a line in a doc, the failure behind it.
- `hooks/scripts/lib.mjs`: target resolution, the `repos.yaml` reader, worktree and `nativePath` helpers (moved from `repo-hooks.mjs`), shared by `pause-check` and `lanes-check` where theirs can be lifted, copied with a "change both" note where it cannot.
- `hooks/scripts/repo-hooks.mjs`, deleted. Its header's session-root finding and the 2026-10-06 test move to `lib.mjs`'s header, because the reason guards are plugin hooks is the same fact.
- `NOTICE.md` and `licenses/`, new.
- `SKILL.md` and `g5-build.md`: "a block naming a repo guard is the harness" becomes "a block naming a guard is this plugin's".

## E22 — Remove every remaining reference

A sweep, last, so the earlier epics do not leave stale text behind.

- **`eval/no-bigin.mjs`** greps the plugin (excluding `CHANGELOG.md`, `specs/` and `.git`) for `bigin-skills`, `bigin-harness`, `bigin-harness-setup`, `task-workflow` and `model-router`, and fails on any hit. It is part of the eval set, so the dependency cannot creep back in a later edit, which is how it spread to 13 files in the first place.
- Docs that change: `README.md` (Install, the "Code repos are created by…" paragraph, the FAQ entry "What if my playbook's stack has no scaffold profile?", which becomes "a playbook with no `scaffold:` block fails Gate 3"), `docs/PLAYBOOK.md` line 363, `docs/img/pipeline.html` if it names the dependency, `.claude-plugin/plugin.json` description if it does.
- **The plugin's own name.** `product-rebuild-skills` appears in the install commands, the command namespace (`/product-rebuild-skills:rebuild`), `README.md`, `docs/PLAYBOOK.md` and the evals. All become `product-rebuild`. `eval/no-bigin.mjs` also fails on the old name outside `CHANGELOG.md` and `specs/`, and on the old repo URL except the README's one pointer line.
- `CHANGELOG.md`: one 1.0.0 entry that says what was removed, what replaced it, and the guards dropped on purpose (context-budget gate, session resume, precompact snapshot). Its first line is the clean-break note: **a workbench on 0.x stays on 0.x until its build is done. 1.x will not open it** (E23).
- `upgrade.mjs`: needs no change for guards (they live in the plugin, nothing vendored into a workbench). It does need to vendor `scaffold.mjs` into the workbench, following its existing manifest rules, if scaffolding is to run from a workbench rather than the plugin root. Open question 4.

## E23 — 1.0.0 ships without moving 0.x

**What has to stay true.** A person mid-rebuild on 0.x must keep a working 0.x. That is harder than it sounds, because three things in the current design would carry 1.x into a 0.x workbench without anyone asking:

1. **`upgrade.mjs --auto` runs at every session start** (`SKILL.md` Step 1) and copies the newest installed plugin's scripts into the workbench. `newestCached` deliberately follows a workbench's marker "to the newest installed version beside it", across any version, so if 1.x is ever installed beside 0.x, a 0.x workbench is upgraded to it.
2. **Plugin hooks load wherever the session starts.** `gate-guard.mjs` and the other workbench guards key on `locks/pipeline.yaml`, which a 0.x workbench has. 1.x's guards would act on a workbench whose repos were created and planned under different rules.
3. **`/plugin update` and auto-update.** The docs (checked 2026-10-26) say nothing lets a marketplace author hold existing installs back from a bump under the same plugin name. So 1.x is not a bump: it is a different plugin, `product-rebuild`, from a different repo, with its own marketplace, cache directory (`cache/product-rebuild/product-rebuild/<version>/`) and `/product-rebuild:` command namespace. An install of `product-rebuild-skills` has no path to it. Moving to 1.x is an install, never an update.

**A fence in 1.x, so 1.x never touches a 0.x workbench.** With separate plugins the upgrade path above cannot cross over, so the fence covers what is left: both plugins enabled in one session, and a person pointing 1.x at a 0.x workbench by hand.

- `rebuild-init.mjs` writes `rebuild_major: 1` into `locks/pipeline.yaml`. A workbench with no such key was made by 0.x, by definition.
- **`upgrade.mjs`** (1.x) refuses a workbench whose `locks/tooling.json` `plugin_version` major, or whose missing `rebuild_major`, says 0.x. It prints one line saying why and which version to stay on, and exits non-zero without copying anything. `--auto` is the session-start path, so this is the case that matters most: a refused `--auto` must be silent-safe (one `TOOLING` line, no copy, no commit). `newestCached` is also changed to stay within the major of the marker it started from, so a 1.x cache directory can never be chosen for a 0.x marker.
- **Every guard hook** exits 0 for a workbench without `rebuild_major: 1`, naming the condition in its comment. The fence is "does nothing for what it was not built for", the same fail-open rule the guards already follow for a missing workbench.
- **`SKILL.md` Step 1 and `commands/rebuild.md`** stop and tell the user: "this workbench was created by 0.x. Install the 0.x line to continue it; 1.x will not open it." They never offer a migration, since none exists.

**0.x gets one last patch, 0.33.1, in `tammai/product-rebuild-skills`, and nothing else.** It makes 0.x's guards exit 0 for a workbench that carries `rebuild_major: 1`, the mirror of the 1.x fence, so that with both plugins enabled in one session (different names both load their hooks; the docs imply it without saying so, so `eval/v0-fence.mjs` assumes the worst) neither acts on the other's workbenches. It is cut from the 0.33.0 tag, ships before 1.0.0, and is the one thing this spec asks of the v0 line. Its only asterisk on "0.x unchanged" is that a 0.x user who has both plugins gets a silent no-op instead of a double guard.

**The v0 line needs no pin and no branch.** `tammai/product-rebuild-skills` keeps its `main`, its `marketplace.json` and its tags exactly as they are, and 0.x fixes, if ever needed, land there. The new repo starts from the same history, so provenance survives, and diverges at the 1.0.0 work. Its `README` opens with one line: "1.x of the pipeline formerly published as `product-rebuild-skills`. It does not continue 0.x workbenches."

**Changes**

- `scripts/rebuild-init.mjs`: write `rebuild_major: 1`.
- `scripts/upgrade.mjs`: the refusal. `newestCached` needs no change, since the two plugins have different cache paths.
- `hooks/scripts/lib.mjs`: one `isV1Workbench(root)`, used by every guard.
- `SKILL.md`, `commands/rebuild.md`: the stop message.
- `.claude-plugin/plugin.json`: `name: product-rebuild`, `version: 1.0.0`, and `homepage`/`repository` at `tammai/product-rebuild`. `.claude-plugin/marketplace.json`: the marketplace and its one entry renamed to `product-rebuild`, `source: ./`.
- `CHANGELOG.md`: the 1.0.0 entry's first line. The 0.33.1 entry goes in the old repo's.
- `eval/v0-fence.mjs`, new: a 0.x-shaped workbench (no `rebuild_major`, `plugin_version: 0.33.0`) beside a fake plugin cache holding both plugins. It asserts that 1.x `upgrade.mjs` refuses without copying, that each 1.x guard exits 0 on it, and that `rebuild-init.mjs` marks a new workbench `rebuild_major: 1`.

## Evals

- **`eval/lane-guards.mjs`**, replacing `eval/repo-hooks.mjs`. It builds a parent directory with a workbench (`repos.yaml`) and a nested repo, feeds hook payloads straight to each guard script, and asserts:
  - bash guard blocks `--no-verify`, `-n` and force push; allows a plain commit;
  - spec gate: an edit over the threshold is blocked with no `PLAN.md`, allowed under `Status: approved` with a matching `Branch:`, blocked under `Status: amending` and under a plan left from another branch; a gate-file edit asks whatever the plan says; a whole-file `Write` of equal length but different content is sized by changed lines;
  - injection: a flagged fetch makes the next risky call ask; a call whose input contains the seeded canary is denied;
  - commit gates: a non-Conventional subject is blocked; a `fix:` with no staged test is blocked, and allowed with one;
  - scoping: the same payloads aimed at a repo **not** in `repos.yaml`, or from a session rooted in no workbench, exit 0 and write nothing;
  - `C:/…` and `/c/…` spellings of the same repo resolve identically;
  - a guard that throws is reported as a block, not a pass;
  - **no guard runs twice** for one payload.
  No model call. The port's safety rests on this one: it asserts the behaviours the 56-of-68 incident was about.
- **`eval/scaffold-repo.mjs`.** A fixture playbook whose generators are stubs (a `mkdir` and a `printf`, so no network). It asserts: `playbook.mjs` rejects a missing or `none` `scaffold:`; `propose` asks only the `ask:` values and any generator input no ADR holds; `contract` rejects a package missing a command; `run-commands` records every exit and fails on a nonzero one; a rerun after an interrupted step resumes at the right one; a modified seeded file is refused with a diff, a generated file is overwritten, a user-owned file is untouched; the thin `CLAUDE.md` is written once and not rewritten.
- **`eval/lane-plan.mjs`** is updated for E20's agent names, and its two copied patterns now point at the spec gate in this repo rather than at bigin's (a "change both" note becomes an import).
- **`eval/no-bigin.mjs`**, E22.
- **Routing**, extended: all six roles resolve under both profiles; `build-lane` and `lane-verifier` print this plugin's agents; effort disagreement for them lands in `warnings`; a stale profile name degrades to the default with a warning, as now.
- **Once by hand, end to end, before the last release:** a real `web-modular-monolith` repo and a real `mobile-flutter` repo created through E19 on a machine with no `bigin-skills` installed (verify with `/plugin list`), five commands green in each; then one lane in each, with one over-threshold edit allowed under the generated plan and blocked under `amending`, and one `FAIL` round and one `PASS` round through `lane-verifier`. The guard code is a port, so this is the check that nothing was lost in it. Re-run when the Claude Code hook payload shape changes.
- **Recall:** `CLAUDE.md` requires `eval/fixtures/rules-recall/` before and after any change to lane R. Nothing here touches `agents/miner.md` or `rule.schema.json`, so it is not re-run, and the PR says so.

## Phasing

**One release, three build phases.** The work lands on a `v1` branch and ships once, as 1.0.0. Nothing between phases is published, so a user never sees a half-migrated plugin. The 0.x line stays in `tammai/product-rebuild-skills` and is not touched by any of it (E23).

The order still matters, because each phase is checked against a real repo before the next starts, and the obvious order is wrong. Scaffolding first would stop bigin creating repos, so new repos would register no guards while `repo-hooks.mjs` still forwarded only to them: the guards would go inert with nothing failing. So the guards move before the repos do.

1. **E21 and E20.** Native guards and the two agents. They work on any repo, bigin-created or not, because they read `PLAN.md`, `repos.yaml` and git state, not anything the harness wrote. `repo-hooks.mjs` is removed in the same phase, so a bigin-created repo's guards do not run twice (its own `settings.json` hooks forward, the plugin's run natively). Check: `eval/lane-guards.mjs`, plus one lane on an existing bigin-created repo.
2. **E19.** `scaffold-repo`, the `scaffold:` playbook block, `g5-build.md` step 0, the G0 and README changes. Check: `eval/scaffold-repo.mjs`, then a real repo from each shipped playbook.
3. **E22 and E23.** The sweep, `eval/no-bigin.mjs` turned on, the v0 fence and release mechanics, the by-hand end-to-end run, docs and CHANGELOG.

Any phase can be backed out alone before release. Phase 1 is the riskiest because it is a port of hardened code; phase 2 has the largest design surface; phase 3 only deletes and fences.

## Open questions

1. **Is `scaffold:` frontmatter or a body section?** Frontmatter keeps it machine-validated at G4a and Gate 3, but generators and templates make the frontmatter long. Recommendation: frontmatter for `packages`, `ask`, `ci`; templates as files under `references/playbooks/<name>/templates/`.
2. **How many path-scoped rules?** The harness wrote a set per stack. `sdlc` ships seven generic ones (`code-style`, `tests`, `migrations`, `sensitive`, `ci`, `ui`, `sdlc`). Recommendation: port those seven as generic seeds, and let the playbook add stack-specific ones. The rules are advice, not a gate, so being too few costs less than being too many.
3. **Fresh clones have no git hooks.** `.git/hooks/` is untracked; bigin's `Setup` hook installed them on a teammate's first Claude run. Recommendation: `scaffold.mjs install-hooks` plus one line in the repo's `CLAUDE.md` pointer, and no `Setup` hook. Rebuild repos are mostly worked by the orchestrator, not cloned by teammates, so this is a rare path. Revisit if a clone ever skips them.
4. **Does scaffolding run from the plugin root or a vendored workbench copy?** Other scripts are vendored so a workbench is a self-contained, versioned copy. `scaffold.mjs` runs once at G5 and needs the plugin's templates, so vendoring it buys little. Recommendation: run from the plugin, do not vendor, and record the plugin version in the lock for drift reporting.
5. **Upgrading a scaffolded repo.** `sdlc` has an upgrade flow for files it placed. This spec has `status --drift` report only, with no applier, because rebuild repos live for one project. Recommendation: report only; build an applier if a second long-lived rebuild asks.
6. **Should `routing.mjs`'s profiles be renamed now that nothing ties them to bigin?** `balanced` and `frontier` read fine and renaming breaks every `model-routing.json`. Recommendation: keep the names.
