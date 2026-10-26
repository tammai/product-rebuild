// lib.mjs — shared prelude for the PreToolUse guards. Every guard reads the hook payload,
// resolves the target file, and walks up to the workbench root (marker: locks/pipeline.yaml).
// Each of those used to be copy-pasted; one copy to fix is the point of this file.
// Every helper fails open: it exits 0 itself when the edit is not one the guards care about.

import { readFileSync, existsSync, readdirSync, realpathSync, statSync } from "node:fs";
import { dirname, resolve, join, isAbsolute } from "node:path";
import { homedir } from "node:os";

export const readPayload = () => {
  try { return JSON.parse(readFileSync(0, "utf8")); } catch { return process.exit(0); }
};

// Returns { payload, abs, root } or exits 0 when there is no target or no workbench above it.
export const locate = () => {
  const payload = readPayload();
  const target = payload?.tool_input?.file_path || payload?.tool_input?.path;
  if (!target) process.exit(0);
  const abs = resolve(payload?.cwd || process.cwd(), target);
  let root = dirname(abs);
  while (root !== dirname(root)) {
    if (existsSync(join(root, "locks", "pipeline.yaml"))) break;
    root = dirname(root);
  }
  if (!existsSync(join(root, "locks", "pipeline.yaml"))) process.exit(0); // not in a workbench
  return { payload, abs, root };
};

// The paths a lock file protects: the `  - x` items of the top-level `protects:` block only,
// not any other indented list in the file (e.g. `history:` entries).
// CRLF is normalised here rather than at each caller: a lock file checked out with
// core.autocrlf=true never matches `^protects:[ \t]*\n`, and an empty list means gate-guard
// lets every edit through to a locked gate.
export const parseProtects = (text) => {
  const block = text.replace(/\r\n?/g, "\n").match(/^protects:[ \t]*\n((?:[ \t]+.*\n?)*)/m);
  if (!block) return [];
  return [...block[1].matchAll(/^  - (.+)$/gm)].map((m) => m[1].trim());
};

// --- Windows: paths written MSYS-style -------------------------------------------------------
// Takes `platform` and `home` as arguments rather than reading process.platform, so
// eval/lane-guards.mjs can check the win32 branch on a POSIX host.

// A path as Node on this platform reads it. On win32 a Bash command written for Git Bash names
// directories MSYS-style (`cd /c/Users/x/app`), which `resolve()` turns into `C:\c\Users\x\app`
// — no repo there, so the guards judged a directory that does not exist and were skipped by
// spelling alone (issue #3 in 0.x). `/c/...` and `/cygdrive/c/...` become `C:/...`; `~` becomes the home directory,
// since HOME is often unset outside Git Bash. Other platforms get only the `~` expansion.
export const nativePath = (p, platform, home) => {
  let s = p.replace(/^~(?=[\\/]|$)/, home || "~");
  if (platform === "win32") s = s.replace(/^\/(?:cygdrive\/)?([a-zA-Z])(?:\/|$)/, (_, d) => `${d.toUpperCase()}:/`);
  return s;
};

// --- Which repos the guards judge ----------------------------------------------------------------
// WHY THE GUARDS NEED A SCOPE. Plugin hooks fire in every session where the plugin is enabled,
// including sessions that have nothing to do with a rebuild. A guard that blocked `git push -f`
// or a 30-line edit in an unrelated project would be a bug in this plugin, so every blocking
// guard judges only a repo the pipeline owns: one listed in the `repos.yaml` of a workbench at
// or near the session root. Anything else fails open (exit 0).
//
// WHERE A WORKBENCH IS LOOKED FOR: the session root, its direct children (the layout
// rebuild-init creates: <project>/<name>-workbench beside the code repos), and — when the
// session root is itself a git repo — its parent's direct children, which is where the workbench
// is for a session started inside a code repo. repos.yaml is read with the same fixed-subset
// regex as scripts/lanes-check.mjs and pause-check.mjs: copied, not imported, since a hook
// cannot depend on a workbench's vendored scripts. If you change one, change all three.
//
// Plugin hooks load wherever a session starts; a code repo's own `.claude/settings.json` does
// not (checked 2026-10-06: a nested repo's hook that blocked every Write was bypassed from a
// parent-rooted session and fired from inside the repo). That is the reason these guards are
// this plugin's hooks and not files written into each repo.

const real = (p) => { try { return realpathSync(p); } catch { return resolve(p); } };
const native = (p) => nativePath(p, process.platform, homedir());

export const sessionRoot = (payload) => process.env.CLAUDE_PROJECT_DIR || payload?.cwd || process.cwd();

const isWorkbench = (d) => existsSync(join(d, "locks", "pipeline.yaml"));
const childDirs = (d) => {
  try { return readdirSync(d, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => join(d, e.name)); }
  catch { return []; } // unreadable root: no workbench found, so the caller fails open
};

export const workbenchesNear = (root) => {
  const found = new Set();
  const scan = (d) => { if (isWorkbench(d)) found.add(d); for (const c of childDirs(d)) if (isWorkbench(c)) found.add(c); };
  scan(root);
  if (existsSync(join(root, ".git"))) for (const c of childDirs(dirname(root))) if (isWorkbench(c)) found.add(c);
  return [...found];
};

// True when a workbench is at or near the session root: the question the session-level hooks
// (canary seed, injection scan) ask, since they judge a session, not a repo.
export const inPipelineSession = (payload) => workbenchesNear(sessionRoot(payload)).length > 0;

export const listedRepos = (workbenches) => {
  const listed = new Set();
  for (const wb of workbenches) {
    const reposFile = join(wb, "repos.yaml");
    if (!existsSync(reposFile)) continue;
    const text = readFileSync(reposFile, "utf8").replace(/\r\n?/g, "\n");
    for (const m of text.matchAll(/^\s*-\s*(?:name:\s*(\S+)\s*)?path:\s*(\S+)/gm)) {
      const p = native(m[2]);
      listed.add(real(isAbsolute(p) ? p : resolve(wb, p)));
    }
  }
  return listed;
};

// { worktree, mainRepo } when `target` (a file or directory, which need not exist yet) lies in a
// git worktree whose main repo is listed for this session, else null. Walks up from the nearest
// directory that exists, because a Write may create several. `.git` is a directory in a main
// checkout and a `gitdir:` file in a linked worktree; reading it directly avoids spawning git on
// every tool call. A lane's worktree counts through its main repo.
export const pipelineRepoOf = (target, payload) => {
  if (!target) return null;
  let dir = resolve(payload?.cwd || sessionRoot(payload), native(target));
  while (!existsSync(dir) && dir !== dirname(dir)) dir = dirname(dir);
  let worktree = null;
  for (let d = dir; d !== dirname(d); d = dirname(d)) {
    if (existsSync(join(d, ".git"))) { worktree = d; break; }
  }
  if (!worktree) return null;
  let mainRepo = worktree;
  try {
    if (statSync(join(worktree, ".git")).isFile()) {
      const gitdir = readFileSync(join(worktree, ".git"), "utf8").match(/^gitdir:\s*(.+)$/m)?.[1]?.trim();
      const m = gitdir && resolve(worktree, gitdir).match(/^(.*)[\\/]\.git[\\/]worktrees[\\/][^\\/]+$/);
      if (m) mainRepo = m[1];
    }
  } catch { /* unreadable .git file: treat the worktree as its own repo */ }
  const listed = listedRepos(workbenchesNear(sessionRoot(payload)));
  return listed.has(real(mainRepo)) || listed.has(real(worktree)) ? { worktree, mainRepo } : null;
};

// --- PLAN.md: the two lines the spec gate reads ---------------------------------------------------
// scripts/lane-plan.mjs writes `Status:` and `Branch:` for these patterns. It is vendored into
// each workbench and must run alone, so it carries its own copy of the format rather than
// importing this; eval/lane-plan.mjs imports both and fails if they stop agreeing. If you change
// a pattern here, change lane-plan.mjs's header and writer with it.
export const PLAN_STATUS = /^Status:\s*(\S+)/m;
export const PLAN_BRANCH = /^Branch:\s*(\S+)/m;
