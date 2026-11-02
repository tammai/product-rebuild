---
name: scaffold-repo
description: Creates one code repo for a rebuild from the locked architecture playbook's scaffold manifest, at G5 step 0. Confirms what the Gate 3 ADRs already decided, asks only what they leave open, shows a proposal for approval, then runs the stack's official generators, writes sdlc's config from the manifest, runs sdlc's setup with the answers the workbench already holds (commands proven on day one, rules, guardrails, CI), and adds the git hooks and a thin CLAUDE.md. Use when rebuild-pipeline reaches G5 and a code repo does not exist yet, or when the user asks to scaffold, create or set up a rebuild's backend, frontend, mobile or other code repo.
---

# Scaffold a code repo

Stack decisions were made at Gate 3 and are locked in `adr/`. This skill does not make them again. It
turns the locked playbook's **scaffold manifest** into a repo whose five commands pass before any
feature exists, so the first lane starts from something that is known to build. The repo is an sdlc
repo: this plugin wraps sdlc, every build lane is an sdlc feature, and sdlc's setup does the parts it
owns (checking and running the commands, rules, guardrails, CI). This skill does what sdlc cannot: the
playbook's generators, and the answers the workbench already holds.

`scripts/scaffold.py` keeps the records exact; you make the judgment calls. Never hand-edit the lock.

```bash
SC="python3 ${CLAUDE_PLUGIN_ROOT}/skills/scaffold-repo/scripts/scaffold.py"   # prints JSON; exit 1 error, exit 2 refused
WB=<path to the rebuild workbench>      # its adr/ holds the locked manifest
```

Run everything from the **new, empty** repo directory (or pass `--dir`). If `git status` there shows
anything, stop: generators refuse a non-empty directory.

## Before anything: is there a manifest?

`adr/playbook.scaffold.json` (vendored with the playbook at G4a) or, when the project chose no
playbook, `adr/scaffold.json`. Gate 3 refused to lock without one, so a missing file means the lock was
forced or the workbench is damaged: say so and stop. Do not improvise a scaffold.

## The procedure

1. **Propose (hard stop).** Read the stack ADRs and the playbook's `scaffold:` choices. For each
   package the manifest offers more than one option for, take the option the ADR locked
   (`--choose api=go`); never decide it here. Then:
   ```bash
   $SC plan --workbench $WB --packages <names> --choose <pkg>=<option> --set <key>=<value>
   ```
   With a value still missing, `plan` lists exactly what to ask and a suggested answer for each. Ask only
   those, a few at a time, each with its suggestion. **A question whose answer is in a locked ADR is a
   bug**: read the ADR. Polyrepo is the default (one repo per package, scaffold one at a time with
   `--packages`); `--monorepo` only if the locked repo-setup ADR says so.
   Show the user the proposal (packages, paths, generator commands, the five commands, what will be
   written) and **wait for approval before generating anything.** Autopilot halts here.

2. **Init.** `$SC init <same flags> --approved-by "<the approver's name>"`. It starts the git repo and
   records the approval.

3. **Skeleton**, once per package: `$SC generate <package>`. It runs the stack's official generator,
   writes the manifest's seed files (a smoke test, lint config, the toolchain pin) and runs the
   install steps. A failing generator is not recorded as done; read its output, fix the cause, rerun
   with `--force`. Never hand-write project files a generator would have produced.
   Commit: `$SC commit "<package> skeleton"`.

4. **sdlc's config**: `$SC sdlc-config`. It writes `.sdlc/config.json` from the manifest: the five commands
   per package, with `test` set to the **fast suite** (the manifest's `test_fast` where it has one; the full
   suite runs only at the slice's joint run), and each package's stack in sdlc's words. It prints
   `sdlc_setup_answers`, which the next step uses. Commit: `$SC commit "sdlc config"`.

5. **sdlc's setup**, the `sdlc:setting-up-projects` skill, in this repo, by its brownfield path (the generator
   wrote source). Answer its hard stops from `sdlc_setup_answers`, not from a fresh interview: the commands
   are already in the config (never re-derive them), the PRD is a pointer to the workbench's product docs, the
   constitution comes from the Gate 3 ADRs, the plugin keys go in the team file, CI is sdlc's with this
   pipeline's license-scan and AC-coverage jobs added to it (and any `ci_pre` lines after the toolchain step).
   Ask the user only what those leave open, in one batch. sdlc's `contract` and `run-commands` are the day-one
   proof: **every command must have run and exited 0**. A failure is fixed in the skeleton, never by changing
   the command; a command edited to pass is a skeleton that does not. A **missing tool** is a stop: installing
   anything is the user's call. At sdlc's last step, merge its `sdlc/setup` branch into `main` locally (the repo
   has no remote yet). Then `$SC step-done sdlc-setup`.

6. **Hooks and pointer**: `$SC render git-hooks`, `$SC render claude-md`, committing after each. A `refused`
   result (exit 2) means a file was edited since it was written: show the user the diff, never overwrite it.
   - `git-hooks`: a `commit-msg` check (Conventional Commits; the same rule the plugin's commit guard
     applies) and a `pre-commit` that runs lint, type-check and the fast tests from sdlc's config. sdlc
     installs no git hooks, and these are the only gate on a commit made outside a Claude session.
   - `claude-md`: a thin pointer (workbench path, where the commands are, the full suite for the joint run).
     It is **not** a rules brief and never gains one; it is the user's file after it is written. sdlc's
     setup never writes `CLAUDE.md`, so nothing overlaps.

7. **Finalize**: `$SC finalize` (moves the lock to `.rebuild/scaffold.lock.json`), commit, then continue
   with the rest of `g5-first-slice.md` step 0: add the workbench submodule **after** this (generators refuse a
   non-empty directory), register the repo in `repos.yaml`, give it a remote, confirm `pause-check` sees
   it.

If the run dies partway, `$SC status` says where it stands (`next:`), and every step before it is
recorded. Resume at that step.

## What this does not do

- It does not build the product's modules. The skeleton is what the generator produces plus one passing
  smoke test per package. The first slice's lane builds the first real module, under a spec the user
  approved. Do not add auth, a database, Docker or infrastructure "for later" unless a locked ADR
  names it for the first slice.
- It does not choose between stacks, and it does not install tools.
- It does not write the guards. This plugin's are its own hooks and judge a repo only once it is
  listed in the workbench's `repos.yaml`, so the repo is **unguarded by them until the checklist registers
  it**; sdlc's guardrails apply from its setup on.

## Hard stops (always ask, and wait)

The proposal · a missing tool · a file the scaffold refuses to overwrite · an sdlc setup question the
workbench does not answer · anything that installs software · the remote's visibility.

## Report

Packages and options, steps done, files by class, the day-one run (each command's exit), anything
skipped and why, and the next step.
