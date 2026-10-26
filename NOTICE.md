# Notice

This plugin includes code adapted from other projects. Their licence texts are in `licenses/`.

## bigin-skills (MIT, Copyright (c) 2026 BigIn)

`licenses/bigin-skills-MIT.txt`. Adapted from `skills/bigin-harness-setup/references/hook-guard.md`
at bigin-skills 1.110.1 (commit `1ade544`), for 1.0.0, then ported from Node to Python:

| Here | From | Changed |
|---|---|---|
| `hooks/scripts/guard_io.py` | `hook-io.mjs` | Cursor host branches removed; `expandHome` goes through `hooklib.py`'s `native_path`; gate-file list rewritten for this plugin; `block_on_crash` added. The shell tokenizer is unchanged. |
| `hooks/scripts/bash_guard.py` | `bash-guard.mjs` | Judges each git invocation by the directory it runs in, and only in a repo listed in a workbench's `repos.yaml`. |
| `hooks/scripts/spec_gate_guard.py` | `spec-gate-guard.mjs` | Same scoping; refusal messages rewritten for the lane-plan flow; `Status: amending` has its own message. |
| `hooks/scripts/commit_gates.py`, `commit_rules.py` | `commit-msg-guard.mjs`, `bugfix-test-guard.mjs` | Merged into one hook; the subject rule is a standalone file so the git `commit-msg` hook can vendor it. |
| `hooks/scripts/injection_scan_guard.py`, `injection_gate_guard.py`, `canary_seed.py` | the same names | Run only in a session with a workbench near its root; temp-file prefix is `rebuild-`. |
| `agents/lane-verifier.md` | `agents/verifier.md` | Rewritten for this pipeline's loop and output contract. |

The injection guards follow a pattern from Lasso Security's open-source PostToolUse Defender:
<https://www.lasso.security/blog/the-hidden-backdoor-in-claude-coding-assistant>.

## sdlc (MIT, tammai/sdlc)

`licenses/sdlc-MIT.txt`. The scaffold-repo skill follows its `setting-up-projects` flow: an
interview that proposes before it generates, official generators over hand-written project files,
the project's own commands recorded and run on day one, files classed by who owns them, and a lock
that refuses to overwrite an edited file. `hooks/py.sh` is adapted from `hooks/sg-python.sh` (the
interpreter probe, the Windows Store stub, MSYS path conversion), cut to what this plugin needs. The
rule seeds in `skills/scaffold-repo/templates/rules/` are adapted from `templates/project/rules/`,
with the test rule rewritten for the once-per-slice test cadence. `agents/lane-verifier.md` takes
that plugin's verifier rules on reporting only what can be evidenced.

## PyYAML 6.0.3 (MIT, Copyright (c) 2017-2021 Ingy döt Net, 2006-2016 Kirill Simonov)

`licenses/pyyaml-MIT.txt`, and a copy beside the code in `skills/rebuild-pipeline/scripts/_vendor/pyyaml/`.
Vendored load-only (reader, scanner, parser, composer, resolver, constructor, loader) so the plugin
needs no `pip install`. One change to the scanner and a replaced `__init__.py` are recorded in
`_vendor/pyyaml/PATCHES.md`. It is reached only through `yamlio.py`.
