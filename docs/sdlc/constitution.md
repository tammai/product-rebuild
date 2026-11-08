# product-rebuild Constitution

Inferred at sdlc setup (2026-11-08) from the repo's scripts, evals and CLAUDE.md; approved under the
coordinator's "recommended defaults" instruction. Amend through `sdlc:project-constitution`.

## Core Principles

### I. Stdlib-only, no install step
Scripts and hooks MUST run on the user's Python 3 with no `pip install`. A third-party library is
vendored (`scripts/_vendor/`, with its licence) only when a hand-written replacement would be less
correct, and the reason is written in the importing module's header.

### II. Deterministic checks live in scripts, judgement in agents
A rule that can be checked mechanically MUST be a script or hook, not a sentence in a prompt. Every
script opens with a header saying what it does, why it exists and why it is a script.

### III. Every behaviour change has an eval
A change to a script, hook or schema MUST come with a case in `skills/rebuild-pipeline/eval/` (or the
fixture's own tests) that fails before the change and passes after. One test per user-visible
behaviour: the happy path plus the failure that matters most. A change to lane R is measured on the
rules-recall fixture before and after.

### IV. No silent pass
A check that cannot run MUST report it did not run (`not run: <reason>`), never pass. Validators
refuse what they do not understand.

### V. Simplicity
Changes MUST be the smallest that meet the acceptance criteria. New abstractions, options, configuration, public exports and dependencies MUST be justified by a current requirement, not a possible future one; an abstraction with a single implementation needs a written reason. Comments MUST explain *why*, never restate the code or its change history; doc comments are for exported API and are one line unless the contract needs more.

### VI. Releases are versioned and recorded
Every release bumps `.claude-plugin/plugin.json` per SemVer and adds a `CHANGELOG.md` entry that
says what changed and why. Breaking changes need a major version.

## Platform constraints

Runs on Windows (Git Bash), macOS and Linux. Paths, line endings and shells MUST be handled for all
three; Windows behaviour is covered by `eval/windows_and_upgrade.py`.

## Review

Work merges to `main` only after review and with the eval suite no worse than `.sdlc/baseline.md`.

## Governance

This constitution overrides other practice in this repo. Amendments are recorded with a date and a reason.

**Version**: 1.0.0 | **Ratified**: 2026-11-08 | **Last Amended**: 2026-11-08
