#!/usr/bin/env node
// commit-rules.mjs — the Conventional-Commit subject rule, written once, usable two ways:
//   import { subjectProblem } from "./commit-rules.mjs"   commit-gates.mjs, the Claude-side check
//   node commit-rules.mjs <msg-file>                      a git `commit-msg` hook
//
// WHY ONE FILE. The rule has to hold for a commit made through Claude (commit-gates.mjs sees
// the `git commit -m` before it runs) and for one made by hand in a terminal (only a git hook
// sees that). Two copies of a regex and a type list drift: one accepts `wip:` and the other does
// not, and a lane learns which to trust. So scaffold-repo vendors THIS file into each code repo
// as `scripts/commit-msg.mjs`, hashes it in the repo's scaffold lock, and refuses to overwrite a
// locally edited copy — one source, and drift is visible instead of silent.
//
// It imports nothing from this plugin, because the vendored copy runs in a repo that has none of
// it. Keep it that way.
//
// FAILS OPEN when it cannot read a subject (no file argument, unreadable file, an empty message):
// the commit-msg hook exists to catch a bad subject, not to turn a git problem into a blocked
// commit. Exit 2 rejects.
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'

export const TYPES = ['feat', 'fix', 'docs', 'style', 'refactor', 'perf', 'test', 'build', 'ci', 'chore', 'revert']
export const CONVENTIONAL = new RegExp(`^(${TYPES.join('|')})(\\([^()]+\\))?!?: .+`)
export const MAX_SUBJECT = 100

// The message to show for a subject that breaks the rule, or null when it is fine. Git's own
// generated subjects and rebase markers are not ours to reformat.
export function subjectProblem(subject) {
  if (!subject) return null
  if (/^(Merge|Revert)\b/.test(subject) || /^(fixup|squash)!/.test(subject)) return null
  if (!CONVENTIONAL.test(subject)) {
    return `Error: commit message is not a Conventional Commit. Use "<type>(<scope>): <subject>" — type one of: ${TYPES.join(', ')}. Append ! before the colon for a breaking change. Got: "${subject}"`
  }
  if (subject.length > MAX_SUBJECT) {
    return `Error: commit subject is ${subject.length} chars (max ${MAX_SUBJECT}). Move the detail into a body: git commit -m "<subject>" -m "<body>".`
  }
  return null
}

// A git commit-msg hook's file: the first line that is neither a comment nor blank. The file
// still carries git's comment template and any scissors line at this point.
export function subjectFromFile(path) {
  for (const line of readFileSync(path, 'utf-8').replace(/\r\n?/g, '\n').split('\n')) {
    if (line.startsWith('#') || line.trim() === '') continue
    return line.trim()
  }
  return null
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let problem = null
  try {
    problem = process.argv[2] ? subjectProblem(subjectFromFile(process.argv[2])) : null
  } catch {
    process.exit(0) // unreadable input → can't judge → never block on guard failure
  }
  if (problem) {
    console.error(problem)
    process.exit(2)
  }
}
