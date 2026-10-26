#!/usr/bin/env node
// bash-guard.mjs — PreToolUse(Bash): blocks a git command that bypasses the commit gates, and
// asks before a command that writes to the gates' own files.
//
// WHY IT IS A HOOK. A lane that is told "never --no-verify" and meets a failing pre-commit hook
// at 2am is a lane that will try it; the instruction does not stop the command, a hook does. It
// is also the only thing between a lane and `git config core.hooksPath /dev/null`, `git push -f`
// or a `+refspec`, which the pre-commit and commit-msg git hooks cannot see because they are
// what is being bypassed.
//
// SCOPE. Plugin hooks fire in every session, so this judges each git invocation by the
// directory it runs in (after any `cd` and its own `-C`) and ignores one that is not in a repo
// listed in a workbench's repos.yaml (lib.mjs pipelineRepoOf). A command that names no
// directory is judged by the session's cwd, which in a parent-rooted session is no repo — so the
// build-lane brief tells lanes to start every command with `cd <worktree> &&`. That gap is real
// and this hook cannot close it. A command it cannot parse blocks inside a pipeline session and
// passes outside one: a tokenizer bug must not stop work in an unrelated project.
//
// Ported in 1.0.0 from the harness this plugin used to depend on (MIT, BigIn; see NOTICE.md).
// Self-filtering: a call with no git in it exits 0. Exit 2 blocks.
import { resolve } from 'node:path'
import {
  readPayload, blockOnCrash, toolCall, stringField, commandDir, projectDir, emitDecision, gitInvocations, commandWalk,
  parseOptions, isLong, COMMIT_GRAMMAR, UNKNOWN, progName, realPath, worktreeRoot, repoRelative, isGateFile
} from './guard-io.mjs'
import { pipelineRepoOf, inPipelineSession } from './lib.mjs'

const data = readPayload('bash-guard.mjs')
blockOnCrash('bash-guard.mjs', data)
const command = stringField(toolCall(data).input, 'command', 'bash-guard.mjs')

const NO_VERIFY = 'Error: --no-verify bypasses pre-commit gates. Fix the underlying issue.'
const COMMIT_N = 'Error: git commit -n bypasses pre-commit gates. Fix the underlying issue.'
const HOOKS_OFF = 'Error: overriding core.hooksPath, the git config the hooks read, or the hook manager bypasses the commit gates. Fix the underlying issue.'
const FORCE = 'Error: force push is blocked. Use --force-with-lease on a feature branch.'
const COMMIT_TREE = 'Error: git commit-tree writes a commit without running any commit hook. Use git commit.'
const COMPUTED = 'Error: this git commit/push takes an argument the shell computes ($VAR, $(…), backticks), so the gate cannot see what it becomes. Write the flags, paths and refspecs literally.'

// Subcommands where --no-verify skips a hook.
const VERIFYING = new Set(['commit', 'push', 'merge', 'pull', 'am', 'rebase', 'revert', 'cherry-pick'])
const PUSH_GRAMMAR = { shortWithArg: 'o', longWithArg: ['--repo', '--receive-pack', '--exec', '--push-option'] }
const OTHER_GRAMMAR = { shortWithArg: 'mF', longWithArg: ['--message', '--file'] }
// Config that moves the hooks, or loads other config that could: core.hooksPath and any
// include / includeIf path.
const HOOKS_PATH_KEY = /^(core\.hookspath|include\.path|includeif\..*\.path)$/i
// Config that turns a plain push into a forced one: remote.<x>.mirror, or a
// remote.<x>.push refspec that starts with `+`.
const FORCE_KEY = /^remote\..*\.(mirror|push)$/i
function forces(key, value) {
  if (!FORCE_KEY.test(key)) return false
  if (/\.mirror$/i.test(key)) return !/^(false|no|off|0)$/i.test(value ?? 'true')
  return /^\+|:\+/.test(value ?? '')
}
const configPair = c => (c.includes('=') ? [c.slice(0, c.indexOf('=')), c.slice(c.indexOf('=') + 1)] : [c, undefined])

// Environment that points git at other config or another git dir, or switches a hook
// manager off. Any of it on a hook-running command is a way past the hooks.
function envSkipsHooks(env) {
  return Object.entries(env).some(([k, v]) => /^GIT_CONFIG/.test(k) || k === 'GIT_DIR' || k === 'GIT_COMMON_DIR'
    || (k === 'HUSKY' && v !== '1') || k === 'HUSKY_SKIP_HOOKS' || k === 'SKIP_SIMPLE_GIT_HOOKS')
}

// `git config core.hooksPath X`, `--unset`, `set`/`unset`: a write. A lone key or --get is a read.
function writesKey(args, keyTest) {
  const at = args.findIndex(a => keyTest(a))
  if (at === -1) return false
  if (args.some(a => /^(get|--get|--get-all|--get-regexp|--list|-l)$/.test(a))) return false
  return args.slice(at + 1).length > 0 || args.some(a => /^(set|unset|--unset|--unset-all|--add|--replace-all)$/.test(a))
}

function verdict(inv) {
  if (inv.unknown) return COMPUTED
  // Plumbing that writes a commit object with no hook run at all.
  if (inv.sub === 'commit-tree') return COMMIT_TREE
  if (inv.config.some(c => c.includes(UNKNOWN) || HOOKS_PATH_KEY.test(c.split('=')[0]))) return HOOKS_OFF
  if (inv.sub === 'push' && inv.config.some(c => forces(...configPair(c)))) return FORCE
  if (inv.sub === 'config') {
    if (writesKey(inv.args, a => HOOKS_PATH_KEY.test(a))) return HOOKS_OFF
    const fk = inv.args.findIndex(a => FORCE_KEY.test(a))
    if (fk !== -1 && writesKey(inv.args, a => FORCE_KEY.test(a)) && forces(inv.args[fk], inv.args[fk + 1])) return FORCE
    // An alias written now is used later in the same line, before any lookup could see it.
    const at = inv.args.findIndex(a => /^alias\./i.test(a))
    if (at !== -1) {
      const body = inv.args.slice(at + 1).filter(a => a !== 'set').join(' ')
      const shell = body.startsWith('!') ? body.slice(1) : `git ${body}`
      for (const aliased of gitInvocations(shell, { cwd: inv.dir ?? undefined })) {
        const v = verdict(aliased)
        if (v) return v
      }
    }
    return null
  }
  if (!VERIFYING.has(inv.sub)) return null
  if (envSkipsHooks(inv.env)) return HOOKS_OFF

  const grammar = inv.sub === 'commit' ? COMMIT_GRAMMAR : inv.sub === 'push' ? PUSH_GRAMMAR : OTHER_GRAMMAR
  const { opts, positionals } = parseOptions(inv.args, grammar)
  // Exact, or the unambiguous prefix git itself accepts (--no-veri).
  if (opts.some(([name]) => isLong(name, '--no-verify', 6))) return NO_VERIFY
  if (inv.sub === 'commit' && opts.some(([name]) => name === '-n')) return COMMIT_N
  if (inv.sub === 'commit' || inv.sub === 'push') {
    // A computed word in flag or operand position could expand to anything, -n included.
    if (opts.some(([name]) => name.includes(UNKNOWN)) || positionals.some(p => p.startsWith(UNKNOWN))) return COMPUTED
  }
  if (inv.sub === 'push') {
    const lease = opts.some(([name]) => isLong(name, '--force-with-lease', 9))
    // --force-with-lease is the sanctioned alternative and never matches these.
    if (opts.some(([name]) => name === '-f' || isLong(name, '--force', 6) || isLong(name, '--mirror', 5))) return FORCE
    if (!lease && opts.some(([name]) => isLong(name, '--force-if-includes', 9))) return FORCE
    if (positionals.some(p => p.startsWith('+') || p.includes(':+'))) return FORCE // +refspec forces that ref
  }
  return null
}

// The pre-tokenizer guard, kept as a backstop so nothing it ever blocked gets through.
function legacyVerdict() {
  let scrubbed = command.replace(/'[^']*'/g, '\'\'')
  scrubbed = scrubbed.replace(/"[^"]*"/g, '""')
  if (/--no-verify/.test(scrubbed)) return NO_VERIFY
  if (/git\s+commit\s+(?:-\w+\s+)*-n\b/.test(scrubbed)) return COMMIT_N
  if (/git\s+push\b.*--force(?!-with-lease)(\s|$)/.test(scrubbed)) return FORCE
  if (/git\s+push\b.*\s-f(\s|$)/.test(scrubbed)) return FORCE
  return null
}

// Must name the same paths guard-io.mjs's GATE_FILES does: if you change one, change both.
const GATE_PATH_TEXT = /(?:\.claude\/settings|\.git\/(?:hooks|config)|\.husky|scripts\/git-hooks|scripts\/(?:pre-commit|commit-msg))[^'"`\s),;]*/g

// Paths a simple command writes, deletes or re-points: redirection targets, tee, sed -i,
// and the operands of cp/mv/rm/ln/truncate/chmod… — so `echo > .claude/guards/x.mjs`
// asks just as an Edit of that file does.
function writeTargets(c) {
  const out = c.redirects.filter(r => r.op.includes('>')).map(r => r.target)
  const name = progName(c.argv[0])
  const operands = c.argv.slice(1).filter(w => !w.startsWith('-'))
  if (name === 'tee' || name === 'rm' || name === 'rmdir' || name === 'unlink' || name === 'mv'
    || name === 'truncate' || name === 'shred' || name === 'chmod' || name === 'chown' || name === 'chgrp') out.push(...operands)
  if ((name === 'sed' || name === 'perl') && c.argv.some(w => /^(-i|--in-place)/.test(w) || /^-[a-zA-Z]*i/.test(w))) out.push(...operands)
  if ((name === 'cp' || name === 'ln' || name === 'install' || name === 'rsync') && operands.length) out.push(operands[operands.length - 1])
  if (name === 'dd') out.push(...c.argv.filter(w => w.startsWith('of=')).map(w => w.slice(3)))
  // An interpreter's script can write anywhere; a gate path written inside it is a target.
  if (/^(python[23]?|node|nodejs|perl|ruby|php|deno|bun)$/.test(name)) {
    for (const w of c.argv.slice(1)) out.push(...(w.match(GATE_PATH_TEXT) ?? []))
  }
  return out
}

function touchesGateFile() {
  const fallback = realPath(projectDir(data))
  for (const c of commandWalk(command, { cwd: commandDir(data) })) {
    for (const target of writeTargets(c)) {
      if (target.includes(UNKNOWN)) continue
      const abs = resolve(c.dir ?? commandDir(data), target)
      if (!pipelineRepoOf(abs, data)) continue
      const rel = repoRelative(abs, worktreeRoot(abs) ?? fallback)
      if (isGateFile(rel)) return rel
    }
  }
  return null
}

const scoped = dir => pipelineRepoOf(dir ?? commandDir(data), data) !== null

let message = null
let gateFile = null
try {
  let anyScoped = false
  for (const inv of gitInvocations(command, { cwd: commandDir(data) })) {
    if (!scoped(inv.dir)) continue
    anyScoped = true
    message = verdict(inv)
    if (message) break
  }
  if (!message && (anyScoped || scoped(null))) message = legacyVerdict()
  if (!message) gateFile = touchesGateFile()
} catch (err) {
  // A parser bug must not turn into exit 1, which Claude Code treats as "allow".
  if (inPipelineSession(data)) {
    message = `Error: bash-guard.mjs could not parse this command (${err.message}) — blocking rather than passing it through unchecked.`
  }
}

if (message) {
  console.error(message)
  process.exit(2) // exit 2 = block the tool call, on both hosts
}

if (gateFile) {
  emitDecision(
    'ask',
    `This command writes ${gateFile}, which is part of this repo's commit and edit gates — a change there can switch one off. Confirm it is something you asked for.`
  )
}
