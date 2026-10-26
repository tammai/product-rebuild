---
name: scaffold-repo
description: Creates one code repo for a rebuild from the locked architecture playbook's scaffold manifest, at G5 step 0. Confirms what the Gate 3 ADRs already decided, asks only what they leave open, shows a proposal for approval, then runs the stack's official generators, writes the five commands, rules, git hooks, CI and a thin CLAUDE.md, and proves the skeleton passes on day one. Use when rebuild-pipeline reaches G5 and a code repo does not exist yet, or when the user asks to scaffold, create or set up a rebuild's backend, frontend, mobile or other code repo.
---

# Scaffold a code repo

Stack decisions were made at Gate 3 and are locked in `adr/`. This skill does not make them again. It
turns the locked playbook's **scaffold manifest** into a repo whose five commands pass before any
feature exists, so the first lane starts from something that is known to build.

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

4. **Commands.** `$SC commands`, then `$SC contract`. Every package must have all five of
   `install build lint typecheck test` (a stack with no such step says `null`). If `contract` reports a
   **missing tool** (`tools_ok: false`), stop and ask: installing anything is the user's call, and so is
   changing a command in the manifest.
   Then `$SC run-commands`: install first, then each step in each package's directory, every exit
   recorded. **Every command must have run and exited 0.** A failure is fixed in the skeleton, never
   by changing the command; a command edited to pass is a skeleton that does not.

5. **Rules, hooks, CI, pointer**: `$SC render rules`, `$SC render git-hooks`, `$SC render ci`,
   `$SC render claude-md`, committing after each. A `refused` result (exit 2) means a file was edited
   since it was written: show the user the diff, never overwrite it.
   - `rules`: generic path-scoped seeds under `.claude/rules/rebuild-*`. Advice, not a gate.
   - `git-hooks`: a `commit-msg` check (Conventional Commits; the same rule the plugin's commit guard
     applies) and a `pre-commit` that runs lint, type-check and the fast tests.
   - `ci`: one workflow built from `.rebuild/commands.json`, so CI and local runs cannot drift. A stack
     with no known toolchain action gets a `TODO` line: fill it in and tell the user.
   - `claude-md`: a thin pointer (workbench path and the five commands). It is **not** a rules brief and
     never gains one; it is the user's file after it is written.

6. **Finalize**: `$SC finalize` (moves the lock to `.rebuild/scaffold.lock.json`), commit, then continue
   with the rest of `g5-build.md` step 0: add the workbench submodule **after** this (generators refuse a
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
- It does not write the guards. They are the plugin's own hooks and judge a repo only once it is
  listed in the workbench's `repos.yaml`, so the repo is **unguarded until step 6 registers it**.

## Hard stops (always ask, and wait)

The proposal · a missing tool · a file the scaffold refuses to overwrite · adding CI to a repo that
already has CI · anything that installs software · the remote's visibility.

## Report

Packages and options, steps done, files by class, the day-one run (each command's exit), anything
skipped and why, and the next step.
