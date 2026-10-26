#!/usr/bin/env node
// commit-gates.mjs — PreToolUse(Bash): two checks on a `git commit` before it runs.
//   1. The subject is a Conventional Commit (commit-rules.mjs).
//   2. A fix-shaped commit includes a test file: every bug fix ships a regression test.
//
// WHY BOTH ARE HERE. The second depends on the first: "is this a fix?" is read off the `fix:`
// prefix, so a lane that writes `Fixed the bug` is not a fix commit and escapes the test rule.
// Checking the subject first makes the type reliable. The git `commit-msg` hook checks the
// subject too (for commits made outside Claude); only a Claude-side hook can see the staged
// files at the moment a lane commits, which is where the regression-test rule is enforced.
//
// SCOPE. Each `git commit` is judged by the directory it runs in, and ignored unless that is a
// repo listed in a workbench's repos.yaml (lib.mjs pipelineRepoOf). Such a repo is also trusted
// as a place to run git, whichever directory the session started in.
//
// Ported in 1.0.0 from the harness this plugin used to depend on (MIT, BigIn; see NOTICE.md).
// Self-filtering: anything but `git commit` exits 0. Exit 2 blocks.
import { resolve } from 'node:path'
import {
  readPayload, blockOnCrash, toolCall, stringField, commandDir, projectDir, gitInvocations, commitMessage, parseOptions, isLong,
  COMMIT_GRAMMAR, safeGit, realPath, repoRelative
} from './guard-io.mjs'
import { pipelineRepoOf } from './lib.mjs'
import { subjectProblem } from './commit-rules.mjs'

const data = readPayload('commit-gates.mjs')
blockOnCrash('commit-gates.mjs', data)
const command = stringField(toolCall(data).input, 'command', 'commit-gates.mjs')

// Every `git commit` the command would run, tokenized the way bash-guard.mjs does it — so
// `git -C <dir> commit`, `-m"msg"` and a heredoc message are all seen. Each carries the
// directory it runs in (after any `cd` and its own -C), which is whose index it commits.
let commits
try {
  commits = gitInvocations(command, { cwd: commandDir(data) })
    .filter(inv => inv.sub === 'commit' && pipelineRepoOf(inv.dir ?? commandDir(data), data))
} catch {
  process.exit(0) // can't parse it → can't judge; bash-guard.mjs blocks on the same input in a pipeline session
}

const TEST_PATTERNS = [
  /\.test\.[^/\\]+$/i,
  /\.spec\.[^/\\]+$/i,
  /_test\.go$/,
  // Dart/Flutter: `foo_test.dart`. Needed on its own because `integration_test/` is not
  // `test/` — without this a bug fix shipping an integration test is blocked for having no test.
  /_test\.dart$/,
  /(^|[/\\])tests?[/\\]/i,
  /(^|[/\\])__tests__[/\\]/
]

// Docs/config-only fixes have no runtime surface to test — same allowlist as
// spec-gate-guard.mjs (minus its git-ignore check: staged files are tracked by definition).
// If you change one, change both.
const TRIVIAL_PATTERNS = [
  /\.md$/i,
  /\.env\.example$/i,
  /(^|[/\\])graphify-out[/\\]/i,
  /(^|[/\\])(\.eslintrc(\.\w+)?|eslint\.config\.\w+|\.prettierrc(\.\w+)?|prettier\.config\.\w+|tsconfig(\.\w+)?\.json|vite\.config\.\w+|vitest\.config\.\w+|nuxt\.config\.\w+|\.editorconfig|\.gitignore|\.npmrc)$/i
]

// Where this guard will run git: the project and its own worktrees, nowhere else. The
// commit under judgement picks its directory, and a directory picks the config git
// loads — so a `-C` or `--git-dir` aimed outside the project is not followed.
function trustedRoots() {
  const root = realPath(projectDir(data))
  const roots = [root]
  try {
    for (const line of safeGit(['worktree', 'list', '--porcelain'], root).split('\n')) {
      if (line.startsWith('worktree ')) roots.push(realPath(line.slice(9)))
    }
  } catch {
    // not a repo — the project root alone
  }
  return roots
}

function inside(path, roots) {
  const real = realPath(path)
  return roots.some(r => real === r || repoRelative(real, r) !== null)
}

// Files this commit will include: staged, tracked-modified when -a/--all is used, and any
// pathspec named on the command line. Read from the commit's own tree (after a `cd`, its
// -C, its --git-dir/--work-tree) — not from the hook's cwd, which in a parallel-worktree
// run is another tree's (empty) index. Never with the command's own VAR= prefixes or
// config: safeGit() drops GIT_* and pins core.fsmonitor off, because an env prefix that
// sets core.fsmonitor runs code in whatever git process reads that repo. null = not judged.
function filesFor(inv, all, pathspecs) {
  if (inv.dir === null) return null
  const roots = trustedRoots()
  const places = [inv.dir, ...inv.locator.map(l => resolve(inv.dir, l.slice(l.indexOf('=') + 1)))]
  if (!places.every(p => inside(p, roots) || pipelineRepoOf(p, data))) return null
  const git = args => safeGit([...inv.locator, ...args, '--no-ext-diff', '--no-textconv'], inv.dir).split('\n')
  let files = git(['diff', '--cached', '--name-only'])
  if (all) files = files.concat(git(['diff', '--name-only']))
  return files.concat(pathspecs).map(f => f.trim()).filter(Boolean)
}

function needsTest(inv) {
  // No parsable message (editor, --no-edit, a message built by a command) → can't judge → allow.
  const message = commitMessage(inv)
  if (message === null) return false

  // Explicit override: [no-test] in the message (state the reason next to it).
  if (message.includes('[no-test]')) return false

  // Fix-shaped: conventional-commit fix prefix (any line), or bugfix/hotfix anywhere.
  if (!/^\s*fix(\([^)]*\))?!?:/im.test(message) && !/\b(bugfix|hotfix)\b/i.test(message)) return false

  // A fix commit in a directory the shell computes (cd $X) has no index we can name.
  // That is the one fix-shaped case judged unknowable on purpose — it blocks.
  if (inv.dir === null) return 'unknown'

  const { opts, positionals } = parseOptions(inv.args, COMMIT_GRAMMAR)
  const all = opts.some(([name]) => name === '-a' || isLong(name, '--all'))
  let files
  try {
    files = filesFor(inv, all, positionals)
  } catch {
    return false // not a git repo / git unavailable — never block on guard failure
  }
  if (files === null || files.length === 0) return false
  if (files.some(f => TEST_PATTERNS.some(p => p.test(f)))) return false
  if (files.every(f => TRIVIAL_PATTERNS.some(p => p.test(f)))) return false
  return true
}

// The subject first: the fix test below reads the type off it.
for (const inv of commits) {
  const subject = commitMessage(inv)?.split('\n').map(l => l.trim()).find(Boolean)
  const problem = subjectProblem(subject)
  if (problem) {
    console.error(problem)
    process.exit(2)
  }
}

const verdicts = commits.map(needsTest)
if (verdicts.includes('unknown')) {
  console.error('Error: fix commit in a directory this guard cannot resolve (a cd or -C target the shell computes). Write the directory literally so the regression-test check can read its staged files.')
  process.exit(2)
}
if (verdicts.includes(true)) {
  console.error(
    'Error: fix commit with no test file included. Every bug fix ships a regression test. Stage a test covering the bug, or add [no-test] to the commit message with the reason.'
  )
  process.exit(2)
}
