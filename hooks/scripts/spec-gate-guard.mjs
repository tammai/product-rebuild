#!/usr/bin/env node
// spec-gate-guard.mjs — PreToolUse(Write|Edit|MultiEdit|NotebookEdit): blocks a non-trivial edit
// in a pipeline code repo until the worktree's PLAN.md says `Status: approved`, and blocks an
// edit governed by a PLAN.md left over from a different branch. Asks before any edit to the
// gates themselves, whatever its size.
//
// WHY IT EXISTS. In the linear rebuild, 56 of the backend's 68 slice commits added over 20 lines
// of non-test code and no PLAN.md ever existed: nothing tied a lane's diff to the slice spec the
// user had approved. The approval already exists — you approve a slice's specs before any code —
// and lane-plan.mjs carries it into PLAN.md at that moment, by script. This hook is what makes
// the plan a precondition instead of a courtesy.
//
// WHY A LANE CANNOT APPROVE ITSELF. `*.md` is exempt below, so nothing here stops a lane writing
// `Status: approved` into its own PLAN.md. The protection is elsewhere: lane-plan.mjs records a
// sha256 of the plan's `## Spec` section, and slice-review.mjs re-checks it at the slice
// boundary, so the edit is visible there. The messages below tell a lane not to try it.
//
// SCOPE. Only a repo listed in a workbench's repos.yaml is judged (lib.mjs pipelineRepoOf);
// anything else exits 0, because this hook fires in every session the plugin is enabled in. The
// plan and the branch are read from the edited file's own worktree, never the session's: a
// parent-rooted session's cwd is no repo, and resolving against it once read another tree's plan.
//
// Ported in 1.0.0 from the harness this plugin used to depend on (MIT, BigIn; see NOTICE.md),
// keeping its four hardening rules. Exit 2 blocks. The Status:/Branch: patterns are lib.mjs's
// PLAN_STATUS and PLAN_BRANCH, which lane-plan.mjs writes for.
import { existsSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { basename, join } from 'node:path'
import {
  readPayload, blockOnCrash, toolCall, stringField, isWriteShaped, emitDecision, realPath, worktreeRoot, repoRelative,
  isGateFile
} from './guard-io.mjs'
import { pipelineRepoOf, PLAN_STATUS, PLAN_BRANCH } from './lib.mjs'

const data = readPayload('spec-gate-guard.mjs')
blockOnCrash('spec-gate-guard.mjs', data)
const call = toolCall(data)
const toolInput = call.input
// Any field this gate reads, present with the wrong type, fails closed (exit 2).
// NotebookEdit names its target `notebook_path`, not `file_path`.
const filePath = stringField(toolInput, 'file_path', 'spec-gate-guard.mjs')
  || stringField(toolInput, 'notebook_path', 'spec-gate-guard.mjs')
for (const field of ['content', 'old_string', 'new_string', 'new_source', 'cell_id', 'edit_mode']) {
  stringField(toolInput, field, 'spec-gate-guard.mjs')
}

if (!filePath) process.exit(0)

// Self-filter on shape as well as on the registered matcher, so a tool added later that carries
// file content is gated without hooks.json being updated first.
if (!isWriteShaped(call)) process.exit(0)

if (!pipelineRepoOf(filePath, data)) process.exit(0) // not a repo the pipeline owns

// A hook's process.cwd() is the session root, which is not the worktree the edited
// file lives in. Resolving the plan and the branch against cwd reads another tree's
// state — it blocked every non-trivial edit in a parallel-worktree run despite an
// approved plan beside the file, and worse, let a main-worktree plan wave through an
// edit in a worktree that had none. Both resolve against the target file's tree, found
// from the nearest directory that exists (a Write may create several). Only a file in
// no repository at all falls back to the session root.
const repoRoot = worktreeRoot(filePath)
const root = repoRoot ?? realPath(data?.cwd || process.cwd())

// Every path rule below judges the real path relative to that root — never the raw
// string, where `src/test/../app.ts` or a repo cloned under ~/tests/ matched "tests/".
// A file outside the root is judged by its name alone.
const rel = repoRelative(filePath, root)

// The gates' own inputs (isGateFile() in guard-io.mjs). A one-line edit to a guard or its
// registration turns a gate off for every later call — exactly what an injected
// instruction would ask for — so the size threshold and an approved plan are both
// beside the point: a person confirms.
if (isGateFile(rel)) {
  emitDecision(
    'ask',
    `${rel} is part of this repo's commit and edit gates — a change here can switch one off. Confirm this edit is one you asked for.`
  )
  process.exit(0)
}

// Trivial paths never require an approved plan: tests (both directory-named and
// `*_test.dart`-named), docs, env examples, config files, and generated graph artifacts (graphify-out/ is committed by design, so the
// git-ignore check below can't cover it).
const TRIVIAL_PATTERNS = [
  /(^|[/\\])tests?[/\\]/i,
  // Dart/Flutter: `foo_test.dart`. Needed on its own for the same reason
  // bugfix-test-guard.mjs needs it — `integration_test/` is not `test/`, so the
  // directory rule above misses every flow test, and a flow test is never ≤20 lines.
  /_test\.dart$/,
  /\.md$/i,
  /\.env\.example$/i,
  /(^|[/\\])graphify-out[/\\]/i,
  /(^|[/\\])(\.eslintrc(\.\w+)?|eslint\.config\.\w+|\.prettierrc(\.\w+)?|prettier\.config\.\w+|tsconfig(\.\w+)?\.json|vite\.config\.\w+|vitest\.config\.\w+|nuxt\.config\.\w+|\.editorconfig|\.gitignore|\.npmrc)$/i
]

if (TRIVIAL_PATTERNS.some(p => p.test(rel ?? basename(filePath)))) process.exit(0)

// Build output and local caches aren't reviewable source: a git-ignored path never
// reaches the diff a plan is written against, so the gate has nothing to govern there.
// Deliberately index-aware (no --no-index) — a *tracked* file that merely matches a
// gitignore pattern is still gated, which is why graphify-out/ needs its rule above.
// Asked of the file's own repo, not of whatever repo the hook happens to run in.
function isGitIgnored() {
  if (!repoRoot) return false
  try {
    execFileSync('git', ['-C', repoRoot, 'check-ignore', '-q', '--', realPath(filePath)], { stdio: 'ignore' })
    return true
  } catch {
    return false // exit 1 = not ignored; 128 = unusable path
  }
}

if (isGitIgnored()) process.exit(0)

function currentBranch() {
  try {
    const b = execFileSync('git', ['-C', root, 'rev-parse', '--abbrev-ref', 'HEAD'], {
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'ignore']
    }).trim()
    return b === 'HEAD' ? null : b // detached HEAD — nothing to compare against
  } catch {
    return null // not a git repo, or git unavailable
  }
}

// { ok: true } | { ok: false, status } | { ok: false, declared, actual } for a branch mismatch.
// `status` is null for a missing plan or one with no Status: line.
function planVerdict() {
  const planPath = join(root, 'PLAN.md')
  if (!existsSync(planPath)) return { ok: false, status: null }
  const plan = readFileSync(planPath, 'utf-8')
  const status = plan.match(PLAN_STATUS)
  if (!status || status[1].toLowerCase() !== 'approved') return { ok: false, status: status?.[1]?.toLowerCase() ?? null }

  // `Branch:` is optional — plans written before it existed, or on a detached HEAD,
  // simply skip the check. Never block on something git can't answer.
  const declared = plan.match(PLAN_BRANCH)?.[1]
  if (!declared) return { ok: true }
  const actual = currentBranch()
  if (!actual || declared === actual) return { ok: true }
  return { ok: false, declared, actual }
}

const verdict = planVerdict()
if (verdict.ok) process.exit(0)

function lines(text) {
  return text === '' ? [] : text.replace(/\r\n/g, '\n').split('\n')
}

// Proxy for the skill's own "≤20 lines of logic" spec-gate exemption.
const LINE_THRESHOLD = 20

// Insertions + deletions between two line lists (Myers' O(ND) diff), or Infinity once
// that passes `max`. Bounded, so a whole-file Write costs O(N·max) and never O(N²).
function lineDistance(a, b, max) {
  const off = max + 1
  const v = new Array(2 * max + 3).fill(0)
  for (let d = 0; d <= max; d++) {
    for (let k = -d; k <= d; k += 2) {
      let x = k === -d || (k !== d && v[off + k - 1] < v[off + k + 1]) ? v[off + k + 1] : v[off + k - 1] + 1
      let y = x - k
      while (x < a.length && y < b.length && a[x] === b[y]) {
        x++
        y++
      }
      v[off + k] = x
      if (x >= a.length && y >= b.length) return d
    }
  }
  return Infinity
}

// A whole-file Write over an existing file is sized by what it changes, the way an Edit
// is: max(lines removed, lines added). Sizing it by the line-count difference let any
// file be replaced wholesale with an equally long one and counted as 0.
function rewriteSize(oldText, newText) {
  const a = lines(oldText)
  const b = lines(newText)
  const d = lineDistance(a, b, 2 * LINE_THRESHOLD + 1) // > 2·threshold means max(…) > threshold
  if (d === Infinity) return Infinity
  const common = (a.length + b.length - d) / 2
  return Math.max(a.length - common, b.length - common)
}

// A NotebookEdit is sized like an Edit of one cell: `insert` adds new_source, `delete`
// removes the cell, `replace` (the default) swaps the cell's source for new_source. The
// old source comes from the notebook itself; a cell we can't find counts as empty for an
// insert or replace, and as unmeasurable for a delete.
function notebookSize() {
  const added = lines(toolInput.new_source ?? '').length
  if (toolInput.edit_mode === 'insert') return added
  let old = null
  try {
    const cell = JSON.parse(readFileSync(filePath, 'utf-8')).cells?.find(c => c.id === toolInput.cell_id)
    if (cell) old = Array.isArray(cell.source) ? cell.source.join('') : String(cell.source ?? '')
  } catch {
    // no such notebook yet, or not JSON — nothing to compare against
  }
  if (toolInput.edit_mode === 'delete') return old === null ? Infinity : lines(old).length
  return old === null ? added : rewriteSize(old, toolInput.new_source)
}

// Keyed on payload shape, not tool name: an unrecognized tool name would otherwise fall
// through to Infinity and block a two-line edit. Unmeasurable input still returns
// Infinity — a change we can't size is one we don't wave through.
function changeSize() {
  if (Array.isArray(toolInput.edits)) {
    return toolInput.edits.reduce(
      (sum, e) => sum + Math.max(lines(e.old_string ?? '').length, lines(e.new_string ?? '').length),
      0
    )
  }
  if (typeof toolInput.old_string === 'string' || typeof toolInput.new_string === 'string') {
    return Math.max(lines(toolInput.old_string ?? '').length, lines(toolInput.new_string ?? '').length)
  }
  if (typeof toolInput.new_source === 'string' || toolInput.edit_mode === 'delete') return notebookSize()
  if (typeof toolInput.content === 'string') {
    if (!existsSync(filePath)) return lines(toolInput.content).length
    try {
      return rewriteSize(readFileSync(filePath, 'utf-8'), toolInput.content)
    } catch {
      return Infinity // exists but unreadable — can't size it
    }
  }
  return Infinity
}

// A malformed `edits` entry must not crash to exit 1, which Claude Code treats as "allow".
function measured() {
  try {
    return changeSize()
  } catch {
    return Infinity
  }
}

if (measured() > LINE_THRESHOLD) {
  const refuse = text => {
    console.error(text)
    process.exit(2)
  }
  if (verdict.declared) {
    refuse(`Error: PLAN.md is for branch '${verdict.declared}' but HEAD is '${verdict.actual}' — a leftover plan from another lane, or the wrong worktree. Do not edit PLAN.md's Branch: line; report it to the orchestrator.`)
  }
  if (verdict.status === 'amending') {
    refuse('Error: PLAN.md is Status: amending — the approved spec was found wrong, so non-trivial edits are frozen until the orchestrator re-approves it. Stop and report what is wrong; do not edit around the freeze.')
  }
  refuse('Error: PLAN.md missing or not approved. A lane\'s PLAN.md is written by the orchestrator (lane-plan.mjs) from the slice specs the user approved. Never write or approve your own. Report it to the orchestrator, or keep the change ≤20 lines.')
}
