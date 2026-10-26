#!/usr/bin/env python3
"""bash_guard.py — PreToolUse(Bash): blocks a git command that bypasses the commit gates, and
asks before a command that writes to the gates' own files.

WHY IT IS A HOOK. A lane that is told "never --no-verify" and meets a failing pre-commit hook
at 2am is a lane that will try it; the instruction does not stop the command, a hook does. It
is also the only thing between a lane and `git config core.hooksPath /dev/null`, `git push -f`
or a `+refspec`, which the pre-commit and commit-msg git hooks cannot see because they are
what is being bypassed.

SCOPE. Plugin hooks fire in every session, so this judges each git invocation by the
directory it runs in (after any `cd` and its own `-C`) and ignores one that is not in a repo
listed in a workbench's repos.yaml (hooklib pipeline_repo_of). A command that names no
directory is judged by the session's cwd, which in a parent-rooted session is no repo — so the
build-lane brief tells lanes to start every command with `cd <worktree> &&`. That gap is real
and this hook cannot close it. A command it cannot parse blocks inside a pipeline session and
passes outside one: a tokenizer bug must not stop work in an unrelated project.

Ported in 1.0.0 from the harness this plugin used to depend on (MIT, BigIn; see NOTICE.md).
Self-filtering: a call with no git in it exits 0. Exit 2 blocks.
"""

import os
import re
import sys

from guard_io import (
    read_payload, block_on_crash, tool_call, string_field, command_dir, project_dir, emit_decision, git_invocations,
    command_walk, parse_options, is_long, COMMIT_GRAMMAR, UNKNOWN, prog_name, real_path, worktree_root, repo_relative,
    is_gate_file, utf8_stdio, JS_SPACE, JS_DOT,
)
from hooklib import pipeline_repo_of, in_pipeline_session

NO_VERIFY = "Error: --no-verify bypasses pre-commit gates. Fix the underlying issue."
COMMIT_N = "Error: git commit -n bypasses pre-commit gates. Fix the underlying issue."
HOOKS_OFF = "Error: overriding core.hooksPath, the git config the hooks read, or the hook manager bypasses the commit gates. Fix the underlying issue."
FORCE = "Error: force push is blocked. Use --force-with-lease on a feature branch."
COMMIT_TREE = "Error: git commit-tree writes a commit without running any commit hook. Use git commit."
COMPUTED = "Error: this git commit/push takes an argument the shell computes ($VAR, $(…), backticks), so the gate cannot see what it becomes. Write the flags, paths and refspecs literally."

# Subcommands where --no-verify skips a hook.
VERIFYING = {"commit", "push", "merge", "pull", "am", "rebase", "revert", "cherry-pick"}
PUSH_GRAMMAR = {"short_with_arg": "o", "long_with_arg": ["--repo", "--receive-pack", "--exec", "--push-option"]}
OTHER_GRAMMAR = {"short_with_arg": "mF", "long_with_arg": ["--message", "--file"]}
# Config that moves the hooks, or loads other config that could: core.hooksPath and any
# include / includeIf path.
HOOKS_PATH_KEY = re.compile(r"^(core\.hookspath|include\.path|includeif\." + JS_DOT + r"*\.path)\Z", re.I | re.A)
# Config that turns a plain push into a forced one: remote.<x>.mirror, or a
# remote.<x>.push refspec that starts with `+`.
FORCE_KEY = re.compile(r"^remote\." + JS_DOT + r"*\.(mirror|push)\Z", re.I | re.A)


def forces(key, value):
    if not FORCE_KEY.search(key):
        return False
    if re.search(r"\.mirror\Z", key, re.I | re.A):
        return not re.search(r"^(false|no|off|0)\Z", value if value is not None else "true", re.I | re.A)
    return bool(re.search(r"^\+|:\+", value if value is not None else ""))


def config_pair(c):
    if "=" in c:
        eq = c.index("=")
        return c[:eq], c[eq + 1:]
    return c, None


def env_skips_hooks(env):
    """Environment that points git at other config or another git dir, or switches a hook
    manager off. Any of it on a hook-running command is a way past the hooks."""
    return any(
        k.startswith("GIT_CONFIG") or k == "GIT_DIR" or k == "GIT_COMMON_DIR"
        or (k == "HUSKY" and v != "1") or k == "HUSKY_SKIP_HOOKS" or k == "SKIP_SIMPLE_GIT_HOOKS"
        for k, v in env.items()
    )


def writes_key(args, key_test):
    """`git config core.hooksPath X`, `--unset`, `set`/`unset`: a write. A lone key or --get is a read."""
    at = next((k for k, a in enumerate(args) if key_test(a)), -1)
    if at == -1:
        return False
    if any(re.fullmatch(r"get|--get|--get-all|--get-regexp|--list|-l", a) for a in args):
        return False
    return len(args[at + 1:]) > 0 or any(re.fullmatch(r"set|unset|--unset|--unset-all|--add|--replace-all", a) for a in args)


def verdict(inv):
    if inv["unknown"]:
        return COMPUTED
    # Plumbing that writes a commit object with no hook run at all.
    if inv["sub"] == "commit-tree":
        return COMMIT_TREE
    if any(UNKNOWN in c or HOOKS_PATH_KEY.search(c.split("=")[0]) for c in inv["config"]):
        return HOOKS_OFF
    if inv["sub"] == "push" and any(forces(*config_pair(c)) for c in inv["config"]):
        return FORCE
    if inv["sub"] == "config":
        if writes_key(inv["args"], lambda a: HOOKS_PATH_KEY.search(a)):
            return HOOKS_OFF
        fk = next((k for k, a in enumerate(inv["args"]) if FORCE_KEY.search(a)), -1)
        if fk != -1 and writes_key(inv["args"], lambda a: FORCE_KEY.search(a)) and forces(inv["args"][fk], inv["args"][fk + 1] if fk + 1 < len(inv["args"]) else None):
            return FORCE
        # An alias written now is used later in the same line, before any lookup could see it.
        at = next((k for k, a in enumerate(inv["args"]) if re.search(r"^alias\.", a, re.I | re.A)), -1)
        if at != -1:
            body = " ".join(a for a in inv["args"][at + 1:] if a != "set")
            shell = body[1:] if body.startswith("!") else f"git {body}"
            for aliased in git_invocations(shell, cwd=inv["dir"]):
                v = verdict(aliased)
                if v:
                    return v
        return None
    if inv["sub"] not in VERIFYING:
        return None
    if env_skips_hooks(inv["env"]):
        return HOOKS_OFF

    grammar = COMMIT_GRAMMAR if inv["sub"] == "commit" else PUSH_GRAMMAR if inv["sub"] == "push" else OTHER_GRAMMAR
    opts, positionals = parse_options(inv["args"], **grammar)
    # Exact, or the unambiguous prefix git itself accepts (--no-veri).
    if any(is_long(name, "--no-verify", 6) for name, _ in opts):
        return NO_VERIFY
    if inv["sub"] == "commit" and any(name == "-n" for name, _ in opts):
        return COMMIT_N
    if inv["sub"] == "commit" or inv["sub"] == "push":
        # A computed word in flag or operand position could expand to anything, -n included.
        if any(UNKNOWN in name for name, _ in opts) or any(p.startswith(UNKNOWN) for p in positionals):
            return COMPUTED
    if inv["sub"] == "push":
        lease = any(is_long(name, "--force-with-lease", 9) for name, _ in opts)
        # --force-with-lease is the sanctioned alternative and never matches these.
        if any(name == "-f" or is_long(name, "--force", 6) or is_long(name, "--mirror", 5) for name, _ in opts):
            return FORCE
        if not lease and any(is_long(name, "--force-if-includes", 9) for name, _ in opts):
            return FORCE
        if any(p.startswith("+") or ":+" in p for p in positionals):
            return FORCE  # +refspec forces that ref
    return None


def legacy_verdict(command):
    """The pre-tokenizer guard, kept as a backstop so nothing it ever blocked gets through."""
    scrubbed = re.sub(r"'[^']*'", "''", command)
    scrubbed = re.sub(r'"[^"]*"', '""', scrubbed)
    if re.search(r"--no-verify", scrubbed):
        return NO_VERIFY
    if re.search(r"git" + JS_SPACE + r"+commit" + JS_SPACE + r"+(?:-\w+" + JS_SPACE + r"+)*-n\b", scrubbed, re.A):
        return COMMIT_N
    if re.search(r"git" + JS_SPACE + r"+push\b" + JS_DOT + r"*--force(?!-with-lease)(" + JS_SPACE + r"|\Z)", scrubbed, re.A):
        return FORCE
    if re.search(r"git" + JS_SPACE + r"+push\b" + JS_DOT + r"*" + JS_SPACE + r"-f(" + JS_SPACE + r"|\Z)", scrubbed, re.A):
        return FORCE
    return None


# Must name the same paths guard_io.py's GATE_FILES does: if you change one, change both.
GATE_PATH_TEXT = re.compile(
    r"(?:\.claude/settings|\.git/(?:hooks|config)|\.husky|scripts/git-hooks|scripts/(?:pre-commit|commit[-_]msg|py\.sh|rebuild_precommit))"
    r"[^'\"`),;" + JS_SPACE[1:-1] + r"]*"
)


def write_targets(c):
    """Paths a simple command writes, deletes or re-points: redirection targets, tee, sed -i,
    and the operands of cp/mv/rm/ln/truncate/chmod… — so `echo > .claude/guards/x.py` asks
    just as an Edit of that file does."""
    out = [r["target"] for r in c["redirects"] if ">" in r["op"]]
    name = prog_name(c["argv"][0] if c["argv"] else None)
    operands = [w for w in c["argv"][1:] if not w.startswith("-")]
    if name in ("tee", "rm", "rmdir", "unlink", "mv", "truncate", "shred", "chmod", "chown", "chgrp"):
        out.extend(operands)
    if name in ("sed", "perl") and any(re.search(r"^(-i|--in-place)", w) or re.search(r"^-[a-zA-Z]*i", w) for w in c["argv"]):
        out.extend(operands)
    if name in ("cp", "ln", "install", "rsync") and operands:
        out.append(operands[-1])
    if name == "dd":
        out.extend(w[3:] for w in c["argv"] if w.startswith("of="))
    # An interpreter's script can write anywhere; a gate path written inside it is a target.
    if re.fullmatch(r"python[23]?|node|nodejs|perl|ruby|php|deno|bun", name):
        for w in c["argv"][1:]:
            out.extend(GATE_PATH_TEXT.findall(w))
    return out


def touches_gate_file(command, data):
    fallback = real_path(project_dir(data))
    for c in command_walk(command, cwd=command_dir(data)):
        for target in write_targets(c):
            if UNKNOWN in target:
                continue
            abs_ = os.path.abspath(os.path.join(c["dir"] if c["dir"] is not None else command_dir(data), target))
            if not pipeline_repo_of(abs_, data):
                continue
            root = worktree_root(abs_)
            rel = repo_relative(abs_, root if root is not None else fallback)
            if is_gate_file(rel):
                return rel
    return None


def main(argv=None):
    utf8_stdio()
    data = read_payload("bash_guard.py")
    block_on_crash("bash_guard.py", data)
    command = string_field(tool_call(data).input, "command", "bash_guard.py")

    def scoped(dir_):
        return pipeline_repo_of(dir_ if dir_ is not None else command_dir(data), data) is not None

    message = None
    gate_file = None
    try:
        any_scoped = False
        for inv in git_invocations(command, cwd=command_dir(data)):
            if not scoped(inv["dir"]):
                continue
            any_scoped = True
            message = verdict(inv)
            if message:
                break
        if not message and (any_scoped or scoped(None)):
            message = legacy_verdict(command)
        if not message:
            gate_file = touches_gate_file(command, data)
    except Exception as err:
        # A parser bug must not turn into exit 1, which Claude Code treats as "allow".
        if in_pipeline_session(data):
            message = f"Error: bash_guard.py could not parse this command ({err}) — blocking rather than passing it through unchecked."

    if message:
        print(message, file=sys.stderr)
        return 2  # exit 2 = block the tool call, on both hosts

    if gate_file:
        emit_decision(
            "ask",
            f"This command writes {gate_file}, which is part of this repo's commit and edit gates — a change there can switch one off. Confirm it is something you asked for.",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
