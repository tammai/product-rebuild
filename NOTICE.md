# Notice

This plugin includes code adapted from other projects. Their licence texts are in `licenses/`.

## bigin-skills (MIT, Copyright (c) 2026 BigIn)

`licenses/bigin-skills-MIT.txt`. Adapted from `skills/bigin-harness-setup/references/hook-guard.md`
at bigin-skills 1.110.1 (commit `1ade544`), for 1.0.0:

| Here | From | Changed |
|---|---|---|
| `hooks/scripts/guard-io.mjs` | `hook-io.mjs` | Cursor host branches removed; `expandHome` goes through `lib.mjs` `nativePath`; gate-file list rewritten for this plugin; `blockOnCrash` added. The shell tokenizer is unchanged. |
| `hooks/scripts/bash-guard.mjs` | `bash-guard.mjs` | Judges each git invocation by the directory it runs in, and only in a repo listed in a workbench's `repos.yaml`. |
| `hooks/scripts/spec-gate-guard.mjs` | `spec-gate-guard.mjs` | Same scoping; refusal messages rewritten for the lane-plan flow; `Status: amending` has its own message. |
| `hooks/scripts/commit-gates.mjs`, `commit-rules.mjs` | `commit-msg-guard.mjs`, `bugfix-test-guard.mjs` | Merged into one hook; the subject rule is a standalone file so the git `commit-msg` hook can vendor it. |
| `hooks/scripts/injection-scan-guard.mjs`, `injection-gate-guard.mjs`, `canary-seed.mjs` | the same names | Run only in a session with a workbench near its root; temp-file prefix is `rebuild-`. |
| `agents/lane-verifier.md` | `agents/verifier.md` | Rewritten for this pipeline's loop and output contract. |

The injection guards follow a pattern from Lasso Security's open-source PostToolUse Defender:
<https://www.lasso.security/blog/the-hidden-backdoor-in-claude-coding-assistant>.
