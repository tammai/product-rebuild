// guard-io.mjs — the hook payload adapter and shell-command tokenizer every guard in this
// directory reads its input through.
//
// WHY IT IS ONE FILE. Every guard here parses one of two things: the hook's JSON payload, or a
// Bash command line. A fix to either has to land in all of them at once — the payload reader
// fails closed so a malformed payload cannot become an ungated call, and the tokenizer is what
// lets bash-guard see `git commit "--no-verify"` or `git -C <dir> push -f` where a regex over
// the raw text saw a quoted string. Six guards with six copies is how one of them would keep the
// old bug.
//
// PROVENANCE. Ported in 1.0.0 from the harness this plugin used to depend on (MIT, BigIn;
// NOTICE.md names the source), with its Cursor host branches removed: this plugin runs under
// Claude Code only, so there is one response envelope and one payload shape. The shell tokenizer below the
// "shell commands" rule is copied unchanged apart from `expandHome`, which now goes through
// lib.mjs's nativePath so `cd /c/Users/x/app` resolves on Windows. See NOTICE.md.
//
// FAIL-CLOSED IS DELIBERATE. A blocking guard that crashes exits 1, and Claude Code treats exit
// 1 as "allow" — the call would run ungated. So everything here that could throw on hostile
// input either exits 2 itself or is wrapped by the caller to do so.
import { existsSync, readFileSync, realpathSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { homedir } from 'node:os'
import { nativePath, inPipelineSession } from './lib.mjs'

// Fail closed for blocking gates: an unparsable payload would otherwise exit 1, which Claude
// Code treats as non-blocking — the call would run ungated. Non-blocking hooks
// (PostToolUse/SessionStart) pass failClosed: false and exit 0 quietly, since they have no
// blocking option and a stack trace is worse than silence.
export function readPayload(guardName, { failClosed = true } = {}) {
  try {
    return JSON.parse(readFileSync(0, 'utf-8'))
  } catch {
    if (!failClosed) process.exit(0)
    console.error(`Error: ${guardName} could not parse its hook payload (empty or malformed stdin) — blocking rather than passing the call through unchecked.`)
    process.exit(2)
  }
}

// A blocking guard that throws exits 1, which Claude Code treats as "allow": the call would run
// ungated, and nothing would say a guard had stopped working. That silent inertness is the
// failure these guards exist to end, so inside a pipeline session a crash is a block with the
// error. Outside one it passes, because this plugin's hooks fire in every session and a bug here
// must not stop work in an unrelated project. If the session check itself throws, that counts
// as a pipeline session: an unknown is not a reason to open the gate.
export function blockOnCrash(guardName, data) {
  process.on('uncaughtException', err => {
    let pipeline = true
    try { pipeline = inPipelineSession(data) } catch { /* unknown: treat as a pipeline session */ }
    if (!pipeline) process.exit(0)
    console.error(`Error: ${guardName} crashed (${err?.message ?? err}) — blocking rather than passing the call through unchecked.`)
    process.exit(2)
  })
}

export function sessionKey(data) {
  return data?.session_id ?? 'unknown'
}

// { name, input } for the tool call this hook is about.
export function toolCall(data) {
  return { name: data?.tool_name ?? '', input: data?.tool_input ?? {} }
}

export function toolOutput(data) {
  // `tool_response` is the current field; `tool_output` is kept for older Claude Code builds.
  return data?.tool_response ?? data?.tool_output ?? ''
}

// A field the hook needs, as a string: absent is ''. Present with any other type, the
// payload is malformed, and a blocking gate exits 2 rather than letting it fall through
// to a crash — an uncaught exception exits 1, which Claude Code treats as "allow".
export function stringField(input, name, guardName) {
  if (input !== undefined && input !== null && typeof input !== 'object') malformed(guardName, 'tool_input')
  const value = input?.[name]
  if (value === undefined || value === null) return ''
  if (typeof value !== 'string') malformed(guardName, name)
  return value
}

function malformed(guardName, field) {
  console.error(`Error: ${guardName} got a malformed ${field} in its hook payload — blocking rather than passing the call through unchecked.`)
  process.exit(2)
}

// git the way a guard runs it: never with the environment or config a command under
// judgement tried to set. Running `git diff` with the command's own GIT_CONFIG_*
// prefixes executed core.fsmonitor (arbitrary code) inside the hook.
export function safeGitEnv() {
  const env = {}
  for (const [k, v] of Object.entries(process.env)) if (!k.startsWith('GIT_')) env[k] = v
  return env
}

export function safeGit(args, cwd) {
  return execFileSync('git', ['-c', 'core.fsmonitor=false', ...args], {
    cwd, env: safeGitEnv(), encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore']
  })
}

function gitOut(args, cwd) {
  return safeGit(args, cwd).trim()
}

// The project root, for hooks that read project state. The fixed root comes first: Claude
// Code's payload `cwd` follows the session into subdirectories, so ranking it first would look
// for the workbench from wherever the last `cd` left the session.
export function projectDir(data) {
  const fixed = process.env.CLAUDE_PROJECT_DIR
  if (fixed) return fixed
  const from = data?.cwd || process.cwd()
  try {
    return gitOut(['rev-parse', '--show-toplevel'], from) || from
  } catch {
    return from // not a repo
  }
}

// The directory a shell command starts in. Unlike projectDir() this is meant to move:
// a Bash call runs where the session currently is, which is what the payload's cwd says.
export function commandDir(data) {
  return data?.cwd || process.cwd()
}

// Read-only tools, named so a write-gate registered without a matcher doesn't gate reads.
const READ_TOOLS = /^(Read|Grep|Glob|Search|List|Task|WebSearch)$/i
const WRITE_TOOLS = /^(Write|Edit|MultiEdit|NotebookEdit|Delete)$/i

// Shape-driven as well as name-driven: a call carrying content/old_string/new_string/
// new_source/edits is a write whatever the tool is called, so a tool added later is gated
// without this list being updated first.
export function isWriteShaped(call) {
  if (READ_TOOLS.test(call.name)) return false
  if (WRITE_TOOLS.test(call.name)) return true
  const input = call.input ?? {}
  return typeof input.content === 'string'
    || typeof input.old_string === 'string'
    || typeof input.new_string === 'string'
    || typeof input.new_source === 'string'
    || Array.isArray(input.edits)
}

// Calls with a side effect or an external surface — what the injection gate's stage-2
// heuristic applies to. Stage 3 (canary) deliberately applies to everything.
export function isRiskyCall(call) {
  return /^(Bash|Shell|Write|Edit|MultiEdit|Delete|WebFetch)$/i.test(call.name)
    || /^(mcp__|MCP:)/.test(call.name)
}

// PreToolUse verdict: 'allow' | 'ask' | 'deny'.
export function emitDecision(decision, reason) {
  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: decision,
      permissionDecisionReason: reason
    }
  }))
}

// Context injection for the non-blocking hooks (PostToolUse, SessionStart).
export function emitContext(event, text) {
  console.log(JSON.stringify({
    hookSpecificOutput: { hookEventName: event, additionalContext: text }
  }))
}

// ── file paths ─────────────────────────────────────────────────────────

// macOS and Windows default to case-insensitive filesystems: API/openapi.yaml IS
// api/openapi.yaml there, so a path compared case-sensitively is a path walked around.
export const CASE_INSENSITIVE_FS = process.platform === 'darwin' || process.platform === 'win32'

// The real, absolute form of a path that may not exist yet. The nearest existing
// ancestor goes through realpath — symlinks, `..`, /tmp vs /private/tmp and (on a
// case-insensitive filesystem) letter case all resolve — and the not-yet-created tail
// is re-attached as typed.
export function realPath(path) {
  let head = resolve(path)
  const tail = []
  for (;;) {
    try {
      return join(realpathSync.native(head), ...tail)
    } catch {
      const up = dirname(head)
      if (up === head) return resolve(path)
      tail.unshift(basename(head))
      head = up
    }
  }
}

// The worktree a path belongs to, or null outside any repo. Never the session's: a
// hook's cwd is the session root, and resolving against it read another tree's PLAN.md
// (v1.90.1). Walks up to the nearest directory that exists, because a Write into a
// brand-new subdirectory has no directory for `git -C` yet — failing there and falling
// back to cwd is how the 1.90.1 fail-open came back.
export function worktreeRoot(path) {
  let dir = dirname(realPath(path))
  while (!existsSync(dir) && dirname(dir) !== dir) dir = dirname(dir)
  try {
    return realPath(gitOut(['rev-parse', '--show-toplevel'], dir))
  } catch {
    return null
  }
}

// `path` relative to `root` with `/` separators, or null when it is not inside root.
// Judge a path by this, never by its raw absolute form: a repo cloned under ~/tests/
// otherwise matches every "tests/" rule, and src/test/../app.ts matches it by typing.
export function repoRelative(path, root) {
  const rel = relative(root, realPath(path))
  if (rel === '' || rel.startsWith('..') || isAbsolute(rel)) return null
  return rel.split(sep).join('/')
}

// The gates' own inputs, as repo-relative paths. A one-line change to any of them turns a gate
// off for every later call — exactly what an injected instruction would ask for — so an edit
// here is confirmed by a person, through Edit/Write or through Bash.
//
// What is listed is what lives IN a code repo. The guards themselves live in this plugin, where
// a lane cannot reach them; the repo-side inputs are the git hooks (they run outside Claude and
// are the last line for a commit made by hand), the vendored commit-msg check, and
// `.claude/settings*.json`, because `"disableAllHooks": true` there would switch every plugin
// guard off for the session. If a path is added to what scaffold-repo installs as a gate, add it
// here too.
const GATE_FILES = /^(\.claude\/settings[^/]*\.json$|\.husky(\/|$)|\.git\/hooks(\/|$)|\.git\/config$|scripts\/git-hooks(\/|$)|scripts\/(pre-commit[^/]*\.sh|commit-msg(\.sh|\.mjs))$)/i

export function isGateFile(rel) {
  return rel !== null && GATE_FILES.test(rel)
}

// ── shell commands ─────────────────────────────────────────────────────
//
// Guards that judge a Bash call tokenize it the way a shell would rather than matching
// a regex against it: a regex cannot tell a flag from a quoted message, so the old
// "scrub the quotes, then match" approach both missed `"--no-verify"` (scrubbed away)
// and needed `-n` to sit right after `commit`. What comes out is every simple command,
// nested ones included — `$( )`, backticks, `( )`, `<( )`, `sh -c`, `eval`, text piped
// or redirected into a shell, and git calls buried in another program's arguments.

// Stands in for text the shell would compute: a $VAR, a command substitution we do not
// run. A word containing it is unknowable, and a guard must not guess what it becomes.
export const UNKNOWN = '\u0000'

const OPERATOR_CHARS = ';&|()<>\n'

// One pass over `src` from `start`. Stops at an unmatched `)` when `inSubst` is set.
// Returns { cmds, end }; each cmd is { words, heredocs, redirects: [{ op, target }] }.
function lex(src, start, inSubst) {
  const cmds = []
  let words = []
  let heredocs = []
  let redirects = []
  let word = null // null = between words; '' = an empty quoted word
  let redirect = null // operator of a redirection whose target is the next word
  let pending = [] // heredoc delimiters waiting for the end of this line
  let parens = 0
  let i = start

  const endWord = () => {
    if (word !== null) {
      if (redirect) redirects.push({ op: redirect, target: word })
      else words.push(word)
      redirect = null
    }
    word = null
  }
  const endCmd = () => {
    endWord()
    redirect = null
    if (words.length || redirects.length || heredocs.length) cmds.push({ words, heredocs, redirects })
    words = []
    heredocs = []
    redirects = []
  }
  const add = (s) => {
    word = (word ?? '') + s
  }
  // `$(`, a backtick or `<(`: lex the inner command, keep its commands, and give the
  // outer word the only value we can know without running anything — a bare
  // `cat <<EOF` heredoc, which is exactly the form a commit message takes.
  const substitute = (inner) => {
    for (const c of inner) cmds.push(c)
    const only = inner.length === 1 ? inner[0] : null
    const isCat = only && only.words.length === 1 && only.words[0] === 'cat' && only.heredocs.length === 1
    add(isCat ? only.heredocs[0].replace(/\n+$/, '') : UNKNOWN)
  }
  // $NAME, ${…}, $1, $@ … — i is on the `$`. Returns false when it is a literal `$`.
  const variable = () => {
    const next = src[i + 1] ?? ''
    if (next === '{') {
      const close = src.indexOf('}', i + 2)
      i = close === -1 ? src.length : close + 1
    } else if (/[A-Za-z_]/.test(next)) {
      i++
      while (/[A-Za-z0-9_]/.test(src[i] ?? '')) i++
    } else if (/[0-9@*#?$!-]/.test(next)) {
      i += 2
    } else return false
    add(UNKNOWN)
    return true
  }
  const readHeredocBodies = () => {
    // Bodies belong to the command that opened them, which this newline has already ended.
    for (const { delim, strip, into } of pending) {
      const lines = []
      while (i < src.length) {
        const nl = src.indexOf('\n', i)
        const line = src.slice(i, nl === -1 ? src.length : nl)
        i = nl === -1 ? src.length : nl + 1
        if ((strip ? line.replace(/^\t+/, '') : line) === delim) break
        lines.push(strip ? line.replace(/^\t+/, '') : line)
      }
      into.push(lines.join('\n') + '\n')
    }
    pending = []
  }
  const backtick = () => {
    const close = src.indexOf('`', i + 1)
    const end = close === -1 ? src.length : close
    substitute(lex(src.slice(i + 1, end).replace(/\\`/g, '`'), 0, false).cmds)
    i = end + 1
  }
  const readDoubleQuoted = () => {
    // i is just past the opening quote
    let s = ''
    while (i < src.length && src[i] !== '"') {
      const c = src[i]
      if (c === '\\' && '$`"\\\n'.includes(src[i + 1] ?? '')) {
        if (src[i + 1] !== '\n') s += src[i + 1]
        i += 2
      } else if (c === '$' && src[i + 1] === '(') {
        add(s)
        s = ''
        const r = lex(src, i + 2, true)
        i = r.end
        substitute(r.cmds)
      } else if (c === '`') {
        add(s)
        s = ''
        backtick()
      } else if (c === '$') {
        add(s)
        s = ''
        if (!variable()) {
          s += c
          i++
        }
      } else {
        s += c
        i++
      }
    }
    add(s)
    i++ // closing quote
  }

  while (i < src.length) {
    const c = src[i]
    if (c === '\\') {
      if (src[i + 1] === '\n') i += 2 // line continuation
      else {
        add(src[i + 1] ?? '')
        i += 2
      }
    } else if (c === '\'') {
      const close = src.indexOf('\'', i + 1)
      const end = close === -1 ? src.length : close
      add(src.slice(i + 1, end))
      i = end + 1
    } else if (c === '$' && src[i + 1] === '\'') {
      // ANSI-C quoting: only the escapes that could hide a flag or a separator
      let s = ''
      i += 2
      while (i < src.length && src[i] !== '\'') {
        if (src[i] === '\\') {
          const e = src[i + 1] ?? ''
          s += e === 'n' ? '\n' : e === 't' ? '\t' : e
          i += 2
        } else s += src[i++]
      }
      add(s)
      i++
    } else if (c === '"' || (c === '$' && src[i + 1] === '"')) {
      i += c === '$' ? 2 : 1
      add('')
      readDoubleQuoted()
    } else if (c === '$' && src[i + 1] === '(') {
      const r = lex(src, i + 2, true)
      i = r.end
      substitute(r.cmds)
    } else if (c === '$' && variable()) {
      // a $VAR: its value is unknowable here
    } else if (c === '`') {
      backtick()
    } else if (c === '#' && word === null) {
      while (i < src.length && src[i] !== '\n') i++
    } else if (c === ' ' || c === '\t') {
      endWord()
      i++
    } else if (c === '\n') {
      endCmd()
      i++
      readHeredocBodies()
    } else if ((c === '<' || c === '>') && src[i + 1] === '(') {
      // Process substitution: the word is a /dev/fd path, the inner command still runs.
      const r = lex(src, i + 2, true)
      i = r.end
      substitute(r.cmds)
    } else if (c === '<' && src[i + 1] === '<' && src[i + 2] !== '<') {
      endWord()
      i += 2
      const strip = src[i] === '-'
      if (strip) i++
      while (src[i] === ' ' || src[i] === '\t') i++
      let delim = ''
      while (i < src.length && !' \t\n;&|<>()'.includes(src[i])) {
        if (src[i] === '\'' || src[i] === '"') {
          const q = src[i]
          const close = src.indexOf(q, i + 1)
          const end = close === -1 ? src.length : close
          delim += src.slice(i + 1, end)
          i = end + 1
        } else if (src[i] === '\\') {
          delim += src[i + 1] ?? ''
          i += 2
        } else delim += src[i++]
      }
      pending.push({ delim, strip, into: heredocs })
    } else if (c === '<' || c === '>') {
      // A bare fd number glued to the operator (2>&1) is part of the redirection.
      if (word !== null && /^\d+$/.test(word)) word = null
      endWord()
      const from = i
      i++
      while ('<>|'.includes(src[i] ?? 'x')) i++
      if (src[i] === '&' && /[\d-]/.test(src[i + 1] ?? '')) {
        i++
        while (/[\d-]/.test(src[i] ?? '')) i++
        continue // >&2 duplicates a descriptor — there is no target word
      }
      if (src[i] === '&') i++
      redirect = src.slice(from, i) // `<<<` here-strings land here too, as op '<<<'
    } else if (c === ')' && inSubst && parens === 0) {
      endCmd()
      return { cmds, end: i + 1 }
    } else if (OPERATOR_CHARS.includes(c)) {
      if (c === '(') parens++
      if (c === ')' && parens > 0) parens--
      if (c === '&' && src[i + 1] === '>') {
        endWord()
        const op = src[i + 2] === '>' ? '&>>' : '&>'
        i += op.length
        redirect = op
        continue
      }
      endCmd()
      i++
    } else {
      add(c)
      i++
    }
  }
  endCmd()
  return { cmds, end: i }
}

const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/
const RESERVED = new Set(['!', '{', '}', 'if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until', 'time', 'noglob', 'nohup', 'builtin', 'exec', 'command', 'busybox'])
const SHELLS = new Set(['sh', 'bash', 'zsh', 'dash', 'ksh', 'ash', 'fish', 'source', '.'])
// Interpreters whose script is code we cannot parse as shell: any git command written
// inside their arguments is dug out and judged on its own.
const INTERPRETERS = new Set(['python', 'python2', 'python3', 'node', 'nodejs', 'perl', 'ruby', 'php', 'deno', 'bun', 'osascript', 'pwsh', 'powershell', 'cmd'])
// Programs that never execute their arguments. Everything else is assumed it might —
// find -exec, xargs, watch, flock, stdbuf, npx, parallel, script… — and a `git` word
// anywhere in its arguments is judged as the git call it would start.
const NON_EXEC = new Set(['echo', 'printf', 'grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack', 'cat', 'less', 'more', 'head',
  'tail', 'man', 'which', 'whereis', 'type', 'hash', 'ls', 'wc', 'sort', 'uniq', 'cut', 'tr', 'jq', 'yq', 'gh', 'glab',
  'test', '[', '[[', 'read', 'unset', 'export', 'local', 'declare', 'history', 'tldr', 'info', 'help', 'cd', 'pushd',
  'popd', 'mkdir', 'touch', 'file', 'stat', 'sleep', 'true', 'false', ':', 'basename', 'dirname', 'realpath',
  'readlink', 'date', 'diff', 'cmp', 'sed', 'tee', 'cp', 'mv', 'rm', 'ln', 'chmod', 'chown', 'git'])

// Program name as the OS would resolve it: /usr/bin/git, git.exe and GIT.EXE are all git.
export function progName(word) {
  const name = (word ?? '').split(/[\\/]/).pop()
  return (CASE_INSENSITIVE_FS ? name.toLowerCase() : name).replace(/\.exe$/i, '')
}

// Drop a leading wrapper's own options. `withArg` lists the options that take a value.
function skipOptions(words, withArg) {
  let j = 0
  while (j < words.length && words[j].startsWith('-') && words[j] !== '-') {
    if (words[j] === '--') return words.slice(j + 1)
    j += withArg.includes(words[j]) ? 2 : 1
  }
  return words.slice(j)
}

// Every `git …` written inside one word — `os.system('git commit -n')`, a watch or
// flock command string — parsed as the shell command it would be.
function gitInside(word, depth) {
  const found = []
  for (const m of word.matchAll(/(^|[^\w./-])git(?=\s)/g)) {
    found.push(...shellCommands(word.slice(m.index + m[1].length), depth + 1))
  }
  return found
}

// Peel assignments and wrappers off one simple command. Returns the command that
// actually runs plus any commands found inside it (sh -c strings, eval, interpreters).
function peel(raw, depth) {
  let words = raw
  const assigns = {}
  const inner = []
  let shellReadsInput = false
  for (;;) {
    while (words.length && ASSIGNMENT.test(words[0])) {
      const eq = words[0].indexOf('=')
      assigns[words[0].slice(0, eq)] = words[0].slice(eq + 1)
      words = words.slice(1)
    }
    if (!words.length) break
    const name = progName(words[0])
    if (name === 'command' && /^-[vV]$/.test(words[1] ?? '')) {
      words = []
      break
    }
    if (RESERVED.has(name)) words = skipOptions(words.slice(1), [])
    else if (name === 'env') {
      const rest = words.slice(1)
      const split = rest.findIndex(w => w === '-S' || w === '--split-string')
      if (split !== -1 && rest[split + 1] !== undefined) {
        rest.splice(split, 2, ...(lex(rest[split + 1], 0, false).cmds[0]?.words ?? []))
      }
      words = skipOptions(rest, ['-u', '--unset', '-C', '--chdir'])
    } else if (name === 'sudo' || name === 'doas') words = skipOptions(words.slice(1), ['-u', '-g', '-C', '-D', '-h', '-p', '-r', '-t', '-U'])
    else if (name === 'xargs') words = skipOptions(words.slice(1), ['-n', '-L', '-P', '-I', '-s', '-d', '-E', '-a'])
    else if (name === 'nice') words = skipOptions(words.slice(1), ['-n'])
    else if (name === 'timeout') words = skipOptions(words.slice(1), ['-s', '-k']).slice(1)
    else if (name === 'eval') {
      inner.push(...shellCommands(words.slice(1).join(' '), depth + 1))
      words = []
    } else if (SHELLS.has(name)) {
      const dashC = words.some((w, k) => k > 0 && /^-[a-zA-Z]*c[a-zA-Z]*$/.test(w))
      if (dashC) {
        // Every operand may be the command string (`-c -- '…'`, `-x -c '…'`): judge each.
        for (const w of words.slice(1)) if (!w.startsWith('-')) inner.push(...shellCommands(w, depth + 1))
        words = []
      } else shellReadsInput = true // reads a script from stdin, a file or <( )
      break
    } else if (INTERPRETERS.has(name)) {
      for (const w of words.slice(1)) inner.push(...gitInside(w, depth))
      break
    } else break
  }
  return { words, assigns, inner, shellReadsInput }
}

// Every simple command in `src` as { argv, assigns, redirects, heredocs }, with leading
// VAR=value assignments split out and wrappers peeled off, so `env X=1 git commit -n`
// reads as the git call it is.
export function shellCommands(src, depth = 0) {
  const out = []
  if (depth > 4) return out
  const peeled = lex(String(src ?? ''), 0, false).cmds.map(c => ({ ...c, ...peel(c.words, depth) }))
  // Text that reaches a shell as its script — `… | sh`, `sh <<EOF`, `sh <<< '…'`,
  // `bash <(echo …)`, `source <(…)` — is judged as commands too. Any word, heredoc or
  // here-string on the same line may be that text, so all of them are parsed.
  const fedToShell = peeled.some(c => c.shellReadsInput)
  for (const c of peeled) {
    const { words, assigns, redirects, heredocs } = c
    if (words.length || Object.keys(assigns).length || redirects.length) out.push({ argv: words, assigns, redirects, heredocs })
    out.push(...c.inner)
    const name = progName(words[0])
    if (words.length && !NON_EXEC.has(name) && !SHELLS.has(name) && !INTERPRETERS.has(name)) {
      // A wrapper we did not peel: find -exec, stdbuf, watch, npx, flock, script, parallel…
      const at = words.findIndex((w, k) => k > 0 && progName(w) === 'git')
      if (at !== -1) out.push({ argv: words.slice(at), assigns, redirects: [], heredocs: [] })
      for (const w of words.slice(1, at === -1 ? words.length : at)) out.push(...gitInside(w, depth))
    }
    if (fedToShell && depth < 4) {
      const texts = [...heredocs, ...redirects.filter(r => r.op === '<<<').map(r => r.target)]
      if (words.length > 1 && !c.shellReadsInput) texts.push(words.slice(1).join(' '))
      for (const text of texts) out.push(...shellCommands(text, depth + 1))
    }
  }
  return out
}

// Builtins git never lets an alias shadow, so naming one needs no alias lookup.
const GIT_BUILTINS = new Set(('add am annotate apply archive bisect blame branch bundle cat-file check-ignore '
  + 'checkout cherry cherry-pick clean clone commit config describe diff difftool fetch for-each-ref '
  + 'format-patch fsck gc grep help init log ls-files ls-remote ls-tree merge merge-base mergetool mv '
  + 'notes pull push range-diff rebase reflog remote repack replace reset restore rev-list rev-parse '
  + 'revert rm shortlog show show-ref sparse-checkout stash status submodule switch symbolic-ref tag '
  + 'update-index update-ref var version worktree').split(' '))

// Global options that take a separate value when written without `=`.
const GIT_GLOBAL_WITH_ARG = new Set(['--git-dir', '--work-tree', '--namespace', '--config-env', '--super-prefix', '--attr-source'])

// On Windows a Git Bash command names directories MSYS-style (`cd /c/Users/x/app`); resolve() alone
// turns that into `C:\c\Users\x\app`, so the guard judged a directory that does not exist and
// the call went unchecked (issue #3 in 0.x). nativePath is the one place that knows the spelling.
const expandHome = p => nativePath(p, process.platform, homedir())

const shellQuote = w => `'${w.replace(/'/g, '\'\\\'\'')}'`

function aliasFor(sub, config, dir, locator) {
  for (const entry of [...config].reverse()) {
    const eq = entry.indexOf('=')
    if (eq !== -1 && entry.slice(0, eq).toLowerCase() === `alias.${sub.toLowerCase()}`) return entry.slice(eq + 1)
  }
  try {
    return gitOut([...locator, 'config', '--get', `alias.${sub}`], dir) || null
  } catch {
    return null // no such alias, or no repo
  }
}

// Every simple command with the directory it runs in — after any earlier `cd`/`pushd`.
// A target the shell would compute (`cd $X`) leaves the directory unknown: `dir` null.
export function commandWalk(command, { cwd = process.cwd() } = {}) {
  const out = []
  let dir = cwd
  for (const c of shellCommands(command)) {
    const name = progName(c.argv[0])
    if (name === 'cd' || name === 'pushd') {
      const target = c.argv.slice(1).find(w => !w.startsWith('-'))
      if (target === undefined) dir = homedir()
      else if (target.includes(UNKNOWN) || dir === null) dir = null
      else if (target !== '-') dir = resolve(dir, expandHome(target))
    }
    out.push({ ...c, dir })
  }
  return out
}

// Every git invocation `command` would run, as
// { sub, args, config, env, dir, locator, unknown }:
//   sub/args  — the subcommand and what follows it, aliases resolved;
//   config    — every `-c key=value` / `--config-env key=…` given before it;
//   env       — VAR=value prefixes and earlier `export`s in the same command line;
//   dir       — the directory git runs in (after any `cd` and its own `-C`s), or null;
//   locator   — its --git-dir/--work-tree/--namespace options, to re-run git as it would;
//   unknown   — the program or subcommand is something the shell computes ($GIT, $(…)).
// Global options before the subcommand are skipped the way git skips them, so
// `git -C . commit -n` and `git -c x=y --no-pager commit -n` are both a commit with -n.
export function gitInvocations(command, { cwd = process.cwd() } = {}) {
  const found = []
  const exported = {}
  const visit = (argv, assigns, dir, depth) => {
    const name = progName(argv[0])
    if (name === 'export') {
      for (const w of argv.slice(1)) {
        const eq = w.indexOf('=')
        if (eq > 0) exported[w.slice(0, eq)] = w.slice(eq + 1)
      }
      return
    }
    // A program word the shell computes ($GIT, git${IFS}commit${IFS}-n) on a line that names
    // a commit or push: what runs cannot be known, so it is judged as unknowable.
    const computed = name.includes(UNKNOWN) && /commit|push/.test(argv.join(' '))
    if ((name !== 'git' && !computed) || depth > 4) return
    const config = []
    const locator = []
    let at = dir
    let j = 1
    while (j < argv.length && argv[j].startsWith('-')) {
      const tok = argv[j]
      const eq = tok.indexOf('=')
      const opt = eq === -1 ? tok : tok.slice(0, eq)
      if (tok === '-C' || (tok.startsWith('-C') && !tok.startsWith('-C='))) {
        const target = tok === '-C' ? argv[j + 1] ?? '.' : tok.slice(2)
        at = at === null || target.includes(UNKNOWN) ? null : resolve(at, expandHome(target))
        j += tok === '-C' ? 2 : 1
      } else if (tok === '-c') {
        config.push(argv[j + 1] ?? '')
        j += 2
      } else if (tok.startsWith('-c')) {
        config.push(tok.slice(2)) // -ckey=value
        j++
      } else if (GIT_GLOBAL_WITH_ARG.has(opt)) {
        const value = eq === -1 ? argv[j + 1] ?? '' : tok.slice(eq + 1)
        if (opt === '--config-env') config.push(value)
        else if (opt !== '--super-prefix' && opt !== '--attr-source') locator.push(`${opt}=${value}`)
        j += eq === -1 ? 2 : 1
      } else j++
    }
    const env = { ...exported, ...assigns }
    let sub = computed ? argv.find(w => w === 'commit' || w === 'push') : argv[j]
    let args = computed ? argv.slice(argv.indexOf(sub) + 1) : argv.slice(j + 1)
    for (let hops = 0; sub && !sub.includes(UNKNOWN) && !GIT_BUILTINS.has(sub) && at !== null && hops < 5; hops++) {
      const alias = aliasFor(sub, config, at, locator)
      if (!alias) break
      if (alias.startsWith('!')) {
        // A shell alias: git runs it with the arguments appended.
        for (const c of commandWalk([alias.slice(1), ...args.map(shellQuote)].join(' '), { cwd: at })) {
          visit(c.argv, { ...env, ...c.assigns }, c.dir, depth + 1)
        }
        sub = null
        break
      }
      const words = lex(alias, 0, false).cmds[0]?.words ?? []
      sub = words[0]
      args = [...words.slice(1), ...args]
    }
    found.push({ sub: sub ?? null, args, config, env, dir: at, locator, unknown: computed || Boolean(sub?.includes(UNKNOWN)) })
  }
  for (const c of commandWalk(command, { cwd })) visit(c.argv, c.assigns, c.dir, 0)
  return found
}

// git's parse-options grammar, enough to tell a flag from a value: short clusters
// (-anm "msg" is -a -n -m "msg"; -mn is -m "n"), attached and separate values,
// --long=value, unambiguous --long prefixes, and `--` ending the options.
// Returns { opts: [name, value][], positionals }.
export function parseOptions(args, { shortWithArg = '', shortOptionalArg = '', longWithArg = [] } = {}) {
  const opts = []
  const positionals = []
  for (let i = 0; i < args.length; i++) {
    const a = args[i]
    if (a === '--') {
      positionals.push(...args.slice(i + 1))
      break
    }
    if (a.startsWith('--')) {
      const eq = a.indexOf('=')
      const name = eq === -1 ? a : a.slice(0, eq)
      const takes = longWithArg.includes(name)
        || (name.length >= 5 && longWithArg.filter(l => l.startsWith(name)).length === 1)
      if (eq !== -1) opts.push([name, a.slice(eq + 1)])
      else opts.push([name, takes ? args[++i] : undefined])
    } else if (a.startsWith('-') && a.length > 1) {
      for (let k = 1; k < a.length; k++) {
        const ch = a[k]
        const rest = a.slice(k + 1)
        if (shortWithArg.includes(ch)) {
          opts.push([`-${ch}`, rest !== '' ? rest : args[++i]])
          break
        }
        if (shortOptionalArg.includes(ch)) {
          opts.push([`-${ch}`, rest])
          break
        }
        opts.push([`-${ch}`, undefined])
      }
    } else positionals.push(a)
  }
  return { opts, positionals }
}

// Long option `name` as typed matches `full` exactly or as git's unambiguous prefix.
export function isLong(name, full, minLength = 5) {
  return name === full || (name.length >= minLength && full.startsWith(name))
}

export const COMMIT_GRAMMAR = {
  shortWithArg: 'mFCct',
  shortOptionalArg: 'Su',
  longWithArg: ['--message', '--file', '--reuse-message', '--reedit-message', '--fixup', '--squash',
    '--author', '--date', '--template', '--cleanup', '--trailer', '--pathspec-from-file']
}

// The message a `git commit` invocation would use, or null when it can't be known
// without running something: no -m/-F (an editor or --no-edit), or a message built
// by a command substitution other than a bare `cat <<EOF` heredoc, or by a $VAR.
export function commitMessage(inv) {
  const parts = []
  for (const [name, value] of parseOptions(inv.args, COMMIT_GRAMMAR).opts) {
    if (name === '-m' || isLong(name, '--message')) parts.push(value ?? '')
    else if (name === '-F' || isLong(name, '--file')) {
      if (!value || value === '-' || inv.dir === null) return null
      try {
        parts.push(readFileSync(resolve(inv.dir, value), 'utf-8').replace(/\n+$/, ''))
      } catch {
        return null
      }
    }
  }
  if (!parts.length) return null
  const message = parts.join('\n\n')
  return message.includes(UNKNOWN) ? null : message
}
