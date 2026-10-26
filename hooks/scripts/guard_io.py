#!/usr/bin/env python3
"""guard_io.py — the hook payload adapter and shell-command tokenizer every guard in this
directory reads its input through.

WHY IT IS ONE FILE. Every guard here parses one of two things: the hook's JSON payload, or a
Bash command line. A fix to either has to land in all of them at once — the payload reader
fails closed so a malformed payload cannot become an ungated call, and the tokenizer is what
lets bash_guard see `git commit "--no-verify"` or `git -C <dir> push -f` where a regex over
the raw text saw a quoted string. Six guards with six copies is how one of them would keep the
old bug.

PROVENANCE. Ported in 1.0.0 from the harness this plugin used to depend on (MIT, BigIn;
NOTICE.md names the source), with its Cursor host branches removed: this plugin runs under
Claude Code only, so there is one response envelope and one payload shape. The shell tokenizer
below the "shell commands" rule is copied unchanged apart from `expand_home`, which now goes
through hooklib's native_path so `cd /c/Users/x/app` resolves on Windows. See NOTICE.md. The
Python port of it follows the JavaScript line by line: a difference in how a quote, a `$(` or a
heredoc is read is exactly how `git commit "--no-verify"` would get through, so the shape of
the code is deliberately the original's.

FAIL-CLOSED IS DELIBERATE. A blocking guard that crashes exits 1, and Claude Code treats exit
1 as "allow" — the call would run ungated. So everything here that could throw on hostile
input either exits 2 itself or is wrapped by the caller to do so.

REGEX DIALECT. The patterns here were written for JavaScript, and three things differ in
Python: `$` also matches before a trailing newline (so `\\Z` is used where JS meant "end"),
`\\d`, `\\w` and `\\b` are Unicode-aware (so re.ASCII or an explicit class is used), and `\\s`
and `.` cover different characters (JS_SPACE and JS_DOT below spell JS's out). A pattern that
drifts from the original is a flag that quietly stops matching.
"""

import json
import os
import re
import subprocess
import sys
from collections import namedtuple

from hooklib import native_path, in_pipeline_session, utf8_stdio, parse_json, read_stdin_text, get

# JS `\s` and the characters `.` refuses to match, for the patterns where Unicode spaces or line
# separators in attacker-chosen text must behave as they did in the original.
JS_SPACE = r"[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
JS_DOT = r"[^\n\r\u2028\u2029]"
_JS_WS_CHARS = "\t\n\x0b\x0c\r \u00a0\u1680" + "".join(chr(c) for c in range(0x2000, 0x200B)) + "\u2028\u2029\u202f\u205f\u3000\ufeff"


def js_trim(s):
    """String.prototype.trim: strips JS's whitespace set, not Python's (which adds \\x1c-\\x1f
    and \\x85 and lacks the BOM)."""
    return s.strip(_JS_WS_CHARS)


def _exit(code):
    # os._exit, not sys.exit: this runs inside sys.excepthook, where SystemExit would be
    # reported as an error in the hook itself and leave a different exit code.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(code)


def read_payload(guard_name, fail_closed=True):
    """Fail closed for blocking gates: an unparsable payload would otherwise exit 1, which Claude
    Code treats as non-blocking — the call would run ungated. Non-blocking hooks
    (PostToolUse/SessionStart) pass fail_closed=False and exit 0 quietly, since they have no
    blocking option and a stack trace is worse than silence."""
    try:
        return parse_json(read_stdin_text())
    except Exception:
        if not fail_closed:
            sys.exit(0)
        print(f"Error: {guard_name} could not parse its hook payload (empty or malformed stdin) — blocking rather than passing the call through unchecked.", file=sys.stderr)
        sys.exit(2)


def block_on_crash(guard_name, data):
    """A blocking guard that throws exits 1, which Claude Code treats as "allow": the call would run
    ungated, and nothing would say a guard had stopped working. That silent inertness is the
    failure these guards exist to end, so inside a pipeline session a crash is a block with the
    error. Outside one it passes, because this plugin's hooks fire in every session and a bug here
    must not stop work in an unrelated project. If the session check itself throws, that counts
    as a pipeline session: an unknown is not a reason to open the gate.

    Installed as sys.excepthook, which Python calls for an exception nothing caught — the
    equivalent of Node's 'uncaughtException'. Not for SystemExit, so a guard's own sys.exit(2)
    is untouched.
    """
    def hook(_exc_type, err, _tb):
        pipeline = True
        try:
            pipeline = in_pipeline_session(data)
        except Exception:
            pass  # unknown: treat as a pipeline session
        if not pipeline:
            _exit(0)
        print(f"Error: {guard_name} crashed ({err}) — blocking rather than passing the call through unchecked.", file=sys.stderr)
        _exit(2)
    sys.excepthook = hook


def session_key(data):
    sid = get(data, "session_id")
    return "unknown" if sid is None else sid


ToolCall = namedtuple("ToolCall", ["name", "input"])


def tool_call(data):
    """(name, input) for the tool call this hook is about."""
    name = get(data, "tool_name")
    tool_input = get(data, "tool_input")
    return ToolCall("" if name is None else name, {} if tool_input is None else tool_input)


def tool_output(data):
    # `tool_response` is the current field; `tool_output` is kept for older Claude Code builds.
    out = get(data, "tool_response")
    if out is None:
        out = get(data, "tool_output")
    return "" if out is None else out


def string_field(input_, name, guard_name):
    """A field the hook needs, as a string: absent is ''. Present with any other type, the
    payload is malformed, and a blocking gate exits 2 rather than letting it fall through
    to a crash — an uncaught exception exits 1, which Claude Code treats as "allow"."""
    if input_ is not None and not isinstance(input_, (dict, list)):
        _malformed(guard_name, "tool_input")
    value = get(input_, name)
    if value is None:
        return ""
    if not isinstance(value, str):
        _malformed(guard_name, name)
    return value


def _malformed(guard_name, field):
    print(f"Error: {guard_name} got a malformed {field} in its hook payload — blocking rather than passing the call through unchecked.", file=sys.stderr)
    sys.exit(2)


def safe_git_env():
    """git the way a guard runs it: never with the environment or config a command under
    judgement tried to set. Running `git diff` with the command's own GIT_CONFIG_*
    prefixes executed core.fsmonitor (arbitrary code) inside the hook."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def safe_git(args, cwd):
    """Runs git and returns its stdout; raises on a non-zero exit, a missing git or a missing cwd,
    as execFileSync did. Output is decoded by hand: text=True would turn CRLF into LF."""
    r = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=cwd, env=safe_git_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, check=True,
    )
    return r.stdout.decode("utf-8", errors="replace")


def _git_out(args, cwd):
    return js_trim(safe_git(args, cwd))


def project_dir(data):
    """The project root, for hooks that read project state. The fixed root comes first: Claude
    Code's payload `cwd` follows the session into subdirectories, so ranking it first would look
    for the workbench from wherever the last `cd` left the session."""
    fixed = os.environ.get("CLAUDE_PROJECT_DIR")
    if fixed:
        return fixed
    from_ = get(data, "cwd") or os.getcwd()
    try:
        return _git_out(["rev-parse", "--show-toplevel"], from_) or from_
    except Exception:
        return from_  # not a repo


def command_dir(data):
    """The directory a shell command starts in. Unlike project_dir() this is meant to move:
    a Bash call runs where the session currently is, which is what the payload's cwd says."""
    return get(data, "cwd") or os.getcwd()


# Read-only tools, named so a write-gate registered without a matcher doesn't gate reads.
READ_TOOLS = re.compile(r"^(Read|Grep|Glob|Search|List|Task|WebSearch)\Z", re.I | re.A)
WRITE_TOOLS = re.compile(r"^(Write|Edit|MultiEdit|NotebookEdit|Delete)\Z", re.I | re.A)


def _name(call):
    return call.name if isinstance(call.name, str) else str(call.name)


def is_write_shaped(call):
    """Shape-driven as well as name-driven: a call carrying content/old_string/new_string/
    new_source/edits is a write whatever the tool is called, so a tool added later is gated
    without this list being updated first."""
    if READ_TOOLS.search(_name(call)):
        return False
    if WRITE_TOOLS.search(_name(call)):
        return True
    input_ = call.input if call.input is not None else {}
    return (isinstance(get(input_, "content"), str)
            or isinstance(get(input_, "old_string"), str)
            or isinstance(get(input_, "new_string"), str)
            or isinstance(get(input_, "new_source"), str)
            or isinstance(get(input_, "edits"), list))


def is_risky_call(call):
    """Calls with a side effect or an external surface — what the injection gate's stage-2
    heuristic applies to. Stage 3 (canary) deliberately applies to everything."""
    name = _name(call)
    return bool(re.search(r"^(Bash|Shell|Write|Edit|MultiEdit|Delete|WebFetch)\Z", name, re.I | re.A)
                or re.search(r"^(mcp__|MCP:)", name))


def emit_decision(decision, reason):
    """PreToolUse verdict: 'allow' | 'ask' | 'deny'."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False, separators=(",", ":")))


def emit_context(event, text):
    """Context injection for the non-blocking hooks (PostToolUse, SessionStart)."""
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": event, "additionalContext": text}
    }, ensure_ascii=False, separators=(",", ":")))


# ── file paths ─────────────────────────────────────────────────────────

# macOS and Windows default to case-insensitive filesystems: API/openapi.yaml IS
# api/openapi.yaml there, so a path compared case-sensitively is a path walked around.
CASE_INSENSITIVE_FS = sys.platform in ("darwin", "win32")


def _realpath_native(head):
    """fs.realpathSync.native: raises when the path does not exist, and on macOS returns the
    on-disk letter case (os.path.realpath does not, which would let `/Users/X/Repo` and
    `/Users/x/repo` compare as two repos)."""
    if not os.path.exists(head):
        raise FileNotFoundError(head)
    resolved = os.path.realpath(head)
    if sys.platform == "darwin":
        try:
            import fcntl
            f_getpath = getattr(fcntl, "F_GETPATH", None)
            if f_getpath is not None:
                fd = os.open(resolved, os.O_RDONLY | os.O_NONBLOCK)
                try:
                    canonical = fcntl.fcntl(fd, f_getpath, bytes(1024)).split(b"\0", 1)[0].decode("utf-8")
                finally:
                    os.close(fd)
                if canonical:
                    return canonical
        except Exception:
            pass  # unreadable or unsupported: the resolved path, in the case it was typed
    return resolved


def real_path(path):
    """The real, absolute form of a path that may not exist yet. The nearest existing
    ancestor goes through realpath — symlinks, `..`, /tmp vs /private/tmp and (on a
    case-insensitive filesystem) letter case all resolve — and the not-yet-created tail
    is re-attached as typed."""
    head = os.path.abspath(path)
    tail = []
    while True:
        try:
            return os.path.join(_realpath_native(head), *tail)
        except OSError:
            up = os.path.dirname(head)
            if up == head:
                return os.path.abspath(path)
            tail.insert(0, os.path.basename(head))
            head = up


def worktree_root(path):
    """The worktree a path belongs to, or None outside any repo. Never the session's: a
    hook's cwd is the session root, and resolving against it read another tree's PLAN.md
    (v1.90.1). Walks up to the nearest directory that exists, because a Write into a
    brand-new subdirectory has no directory for `git -C` yet — failing there and falling
    back to cwd is how the 1.90.1 fail-open came back."""
    d = os.path.dirname(real_path(path))
    while not os.path.exists(d) and os.path.dirname(d) != d:
        d = os.path.dirname(d)
    try:
        return real_path(_git_out(["rev-parse", "--show-toplevel"], d))
    except Exception:
        return None


def repo_relative(path, root):
    """`path` relative to `root` with `/` separators, or None when it is not inside root.
    Judge a path by this, never by its raw absolute form: a repo cloned under ~/tests/
    otherwise matches every "tests/" rule, and src/test/../app.ts matches it by typing."""
    try:
        rel = os.path.relpath(real_path(path), root)
    except ValueError:
        return None  # another drive on Windows: not inside root
    if rel == "." or rel.startswith("..") or os.path.isabs(rel):
        return None
    return "/".join(rel.split(os.sep))


# The gates' own inputs, as repo-relative paths. A one-line change to any of them turns a gate
# off for every later call — exactly what an injected instruction would ask for — so an edit
# here is confirmed by a person, through Edit/Write or through Bash.
#
# What is listed is what lives IN a code repo. The guards themselves live in this plugin, where
# a lane cannot reach them; the repo-side inputs are the git hooks (they run outside Claude and
# are the last line for a commit made by hand), the vendored commit-msg check, and
# `.claude/settings*.json`, because `"disableAllHooks": true` there would switch every plugin
# guard off for the session. If a path is added to what scaffold-repo installs as a gate, add it
# here too, and to GATE_PATH_TEXT in bash_guard.py. The vendored commit-msg check is named
# `commit_msg.py` by scaffold-repo (the hyphenated spelling stays listed because a Python module name
# cannot hyphenate and someone will try), and the launcher and pre-commit runner it vendors beside it.
GATE_FILES = re.compile(
    r"^(\.claude/settings[^/]*\.json\Z|\.husky(/|\Z)|\.git/hooks(/|\Z)|\.git/config\Z|scripts/git-hooks(/|\Z)"
    r"|scripts/(pre-commit[^/]*\.sh|commit[-_]msg(\.sh|\.py)|py\.sh|rebuild_precommit\.py)\Z)",
    re.I | re.A,
)


def is_gate_file(rel):
    return rel is not None and GATE_FILES.search(rel) is not None


# ── shell commands ─────────────────────────────────────────────────────
#
# Guards that judge a Bash call tokenize it the way a shell would rather than matching
# a regex against it: a regex cannot tell a flag from a quoted message, so the old
# "scrub the quotes, then match" approach both missed `"--no-verify"` (scrubbed away)
# and needed `-n` to sit right after `commit`. What comes out is every simple command,
# nested ones included — `$( )`, backticks, `( )`, `<( )`, `sh -c`, `eval`, text piped
# or redirected into a shell, and git calls buried in another program's arguments.

# Stands in for text the shell would compute: a $VAR, a command substitution we do not
# run. A word containing it is unknowable, and a guard must not guess what it becomes.
UNKNOWN = "\u0000"

OPERATOR_CHARS = ";&|()<>\n"


def _lex(src, start, in_subst):
    """One pass over `src` from `start`. Stops at an unmatched `)` when `in_subst` is set.
    Returns {"cmds", "end"}; each cmd is {"words", "heredocs", "redirects": [{"op", "target"}]}."""
    cmds = []
    words = []
    heredocs = []
    redirects = []
    word = None  # None = between words; '' = an empty quoted word
    redirect = None  # operator of a redirection whose target is the next word
    pending = []  # heredoc delimiters waiting for the end of this line
    parens = 0
    i = start
    n = len(src)

    def at(k):
        # src[k] ?? '' — a read past the end is the empty string, which no operator test matches
        return src[k] if 0 <= k < n else ""

    def end_word():
        nonlocal word, redirect
        if word is not None:
            if redirect:
                redirects.append({"op": redirect, "target": word})
            else:
                words.append(word)
            redirect = None
        word = None

    def end_cmd():
        nonlocal words, heredocs, redirects, redirect
        end_word()
        redirect = None
        if words or redirects or heredocs:
            cmds.append({"words": words, "heredocs": heredocs, "redirects": redirects})
        words = []
        heredocs = []
        redirects = []

    def add(s):
        nonlocal word
        word = (word if word is not None else "") + s

    def substitute(inner):
        # `$(`, a backtick or `<(`: lex the inner command, keep its commands, and give the
        # outer word the only value we can know without running anything — a bare
        # `cat <<EOF` heredoc, which is exactly the form a commit message takes.
        cmds.extend(inner)
        only = inner[0] if len(inner) == 1 else None
        is_cat = bool(only) and len(only["words"]) == 1 and only["words"][0] == "cat" and len(only["heredocs"]) == 1
        add(only["heredocs"][0].rstrip("\n") if is_cat else UNKNOWN)

    def variable():
        # $NAME, ${…}, $1, $@ … — i is on the `$`. Returns False when it is a literal `$`.
        nonlocal i
        nxt = at(i + 1)
        if nxt == "{":
            close = src.find("}", i + 2)
            i = n if close == -1 else close + 1
        elif re.match(r"[A-Za-z_]", nxt):
            i += 1
            while re.match(r"[A-Za-z0-9_]", at(i)):
                i += 1
        elif nxt != "" and nxt in "0123456789@*#?$!-":
            i += 2
        else:
            return False
        add(UNKNOWN)
        return True

    def read_heredoc_bodies():
        # Bodies belong to the command that opened them, which this newline has already ended.
        nonlocal i, pending
        for p in pending:
            lines = []
            while i < n:
                nl = src.find("\n", i)
                line = src[i:(n if nl == -1 else nl)]
                i = n if nl == -1 else nl + 1
                seen = line.lstrip("\t") if p["strip"] else line
                if seen == p["delim"]:
                    break
                lines.append(seen)
            p["into"].append("\n".join(lines) + "\n")
        pending = []

    def backtick():
        nonlocal i
        close = src.find("`", i + 1)
        end = n if close == -1 else close
        substitute(_lex(src[i + 1:end].replace("\\`", "`"), 0, False)["cmds"])
        i = end + 1

    def read_double_quoted():
        # i is just past the opening quote
        nonlocal i
        s = ""
        while i < n and src[i] != '"':
            c = src[i]
            nxt = at(i + 1)
            # JS tested `'$`"\\\n'.includes(src[i + 1] ?? '')`, which is true for '' — a lone
            # backslash at the end of an unterminated string appended the text "undefined".
            # Here it stays a literal backslash. Either way the word is not a flag the guards
            # could have matched, and an unterminated quote is the legacy regex's to catch.
            if c == "\\" and nxt != "" and nxt in "$`\"\\\n":
                if nxt != "\n":
                    s += nxt
                i += 2
            elif c == "$" and nxt == "(":
                add(s)
                s = ""
                r = _lex(src, i + 2, True)
                i = r["end"]
                substitute(r["cmds"])
            elif c == "`":
                add(s)
                s = ""
                backtick()
            elif c == "$":
                add(s)
                s = ""
                if not variable():
                    s += c
                    i += 1
            else:
                s += c
                i += 1
        add(s)
        i += 1  # closing quote

    while i < n:
        c = src[i]
        nxt = at(i + 1)
        if c == "\\":
            if nxt == "\n":
                i += 2  # line continuation
            else:
                add(nxt)
                i += 2
        elif c == "'":
            close = src.find("'", i + 1)
            end = n if close == -1 else close
            add(src[i + 1:end])
            i = end + 1
        elif c == "$" and nxt == "'":
            # ANSI-C quoting: only the escapes that could hide a flag or a separator
            s = ""
            i += 2
            while i < n and src[i] != "'":
                if src[i] == "\\":
                    e = at(i + 1)
                    s += "\n" if e == "n" else "\t" if e == "t" else e
                    i += 2
                else:
                    s += src[i]
                    i += 1
            add(s)
            i += 1
        elif c == '"' or (c == "$" and nxt == '"'):
            i += 2 if c == "$" else 1
            add("")
            read_double_quoted()
        elif c == "$" and nxt == "(":
            r = _lex(src, i + 2, True)
            i = r["end"]
            substitute(r["cmds"])
        elif c == "$" and variable():
            pass  # a $VAR: its value is unknowable here
        elif c == "`":
            backtick()
        elif c == "#" and word is None:
            while i < n and src[i] != "\n":
                i += 1
        elif c == " " or c == "\t":
            end_word()
            i += 1
        elif c == "\n":
            end_cmd()
            i += 1
            read_heredoc_bodies()
        elif (c == "<" or c == ">") and nxt == "(":
            # Process substitution: the word is a /dev/fd path, the inner command still runs.
            r = _lex(src, i + 2, True)
            i = r["end"]
            substitute(r["cmds"])
        elif c == "<" and nxt == "<" and at(i + 2) != "<":
            end_word()
            i += 2
            strip = at(i) == "-"
            if strip:
                i += 1
            while at(i) == " " or at(i) == "\t":
                i += 1
            delim = ""
            while i < n and src[i] not in " \t\n;&|<>()":
                if src[i] == "'" or src[i] == '"':
                    q = src[i]
                    close = src.find(q, i + 1)
                    end = n if close == -1 else close
                    delim += src[i + 1:end]
                    i = end + 1
                elif src[i] == "\\":
                    delim += at(i + 1)
                    i += 2
                else:
                    delim += src[i]
                    i += 1
            pending.append({"delim": delim, "strip": strip, "into": heredocs})
        elif c == "<" or c == ">":
            # A bare fd number glued to the operator (2>&1) is part of the redirection.
            if word is not None and re.fullmatch(r"[0-9]+", word):
                word = None
            end_word()
            frm = i
            i += 1
            while at(i) != "" and at(i) in "<>|":
                i += 1
            if at(i) == "&" and re.match(r"[0-9-]", at(i + 1)):
                i += 1
                while re.match(r"[0-9-]", at(i)):
                    i += 1
                continue  # >&2 duplicates a descriptor — there is no target word
            if at(i) == "&":
                i += 1
            redirect = src[frm:i]  # `<<<` here-strings land here too, as op '<<<'
        elif c == ")" and in_subst and parens == 0:
            end_cmd()
            return {"cmds": cmds, "end": i + 1}
        elif c in OPERATOR_CHARS:
            if c == "(":
                parens += 1
            if c == ")" and parens > 0:
                parens -= 1
            if c == "&" and nxt == ">":
                end_word()
                op = "&>>" if at(i + 2) == ">" else "&>"
                i += len(op)
                redirect = op
                continue
            end_cmd()
            i += 1
        else:
            add(c)
            i += 1
    end_cmd()
    return {"cmds": cmds, "end": i}


ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
RESERVED = {"!", "{", "}", "if", "then", "else", "elif", "fi", "do", "done", "while", "until", "time", "noglob", "nohup", "builtin", "exec", "command", "busybox"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "ash", "fish", "source", "."}
# Interpreters whose script is code we cannot parse as shell: any git command written
# inside their arguments is dug out and judged on its own.
INTERPRETERS = {"python", "python2", "python3", "node", "nodejs", "perl", "ruby", "php", "deno", "bun", "osascript", "pwsh", "powershell", "cmd"}
# Programs that never execute their arguments. Everything else is assumed it might —
# find -exec, xargs, watch, flock, stdbuf, npx, parallel, script… — and a `git` word
# anywhere in its arguments is judged as the git call it would start.
NON_EXEC = {"echo", "printf", "grep", "egrep", "fgrep", "rg", "ag", "ack", "cat", "less", "more", "head",
            "tail", "man", "which", "whereis", "type", "hash", "ls", "wc", "sort", "uniq", "cut", "tr", "jq", "yq", "gh", "glab",
            "test", "[", "[[", "read", "unset", "export", "local", "declare", "history", "tldr", "info", "help", "cd", "pushd",
            "popd", "mkdir", "touch", "file", "stat", "sleep", "true", "false", ":", "basename", "dirname", "realpath",
            "readlink", "date", "diff", "cmp", "sed", "tee", "cp", "mv", "rm", "ln", "chmod", "chown", "git"}


def prog_name(word):
    """Program name as the OS would resolve it: /usr/bin/git, git.exe and GIT.EXE are all git."""
    name = re.split(r"[\\/]", word if word is not None else "")[-1]
    if CASE_INSENSITIVE_FS:
        name = name.lower()
    return re.sub(r"\.exe\Z", "", name, flags=re.I | re.A)


def _skip_options(words, with_arg):
    """Drop a leading wrapper's own options. `with_arg` lists the options that take a value."""
    j = 0
    while j < len(words) and words[j].startswith("-") and words[j] != "-":
        if words[j] == "--":
            return words[j + 1:]
        j += 2 if words[j] in with_arg else 1
    return words[j:]


def _git_inside(word, depth):
    """Every `git …` written inside one word — `os.system('git commit -n')`, a watch or
    flock command string — parsed as the shell command it would be."""
    found = []
    for m in re.finditer(r"(^|[^A-Za-z0-9_./-])git(?=" + JS_SPACE + ")", word):
        found.extend(shell_commands(word[m.start() + len(m.group(1)):], depth + 1))
    return found


def _peel(raw, depth):
    """Peel assignments and wrappers off one simple command. Returns the command that
    actually runs plus any commands found inside it (sh -c strings, eval, interpreters)."""
    words = raw
    assigns = {}
    inner = []
    shell_reads_input = False
    while True:
        while words and ASSIGNMENT.search(words[0]):
            eq = words[0].index("=")
            assigns[words[0][:eq]] = words[0][eq + 1:]
            words = words[1:]
        if not words:
            break
        name = prog_name(words[0])
        if name == "command" and re.fullmatch(r"-[vV]", words[1] if len(words) > 1 else ""):
            words = []
            break
        if name in RESERVED:
            words = _skip_options(words[1:], [])
        elif name == "env":
            rest = words[1:]
            split = next((k for k, w in enumerate(rest) if w == "-S" or w == "--split-string"), -1)
            if split != -1 and split + 1 < len(rest):
                first = _lex(rest[split + 1], 0, False)["cmds"]
                rest[split:split + 2] = first[0]["words"] if first else []
            words = _skip_options(rest, ["-u", "--unset", "-C", "--chdir"])
        elif name == "sudo" or name == "doas":
            words = _skip_options(words[1:], ["-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"])
        elif name == "xargs":
            words = _skip_options(words[1:], ["-n", "-L", "-P", "-I", "-s", "-d", "-E", "-a"])
        elif name == "nice":
            words = _skip_options(words[1:], ["-n"])
        elif name == "timeout":
            words = _skip_options(words[1:], ["-s", "-k"])[1:]
        elif name == "eval":
            inner.extend(shell_commands(" ".join(words[1:]), depth + 1))
            words = []
        elif name in SHELLS:
            dash_c = any(k > 0 and re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", w) for k, w in enumerate(words))
            if dash_c:
                # Every operand may be the command string (`-c -- '…'`, `-x -c '…'`): judge each.
                for w in words[1:]:
                    if not w.startswith("-"):
                        inner.extend(shell_commands(w, depth + 1))
                words = []
            else:
                shell_reads_input = True  # reads a script from stdin, a file or <( )
            break
        elif name in INTERPRETERS:
            for w in words[1:]:
                inner.extend(_git_inside(w, depth))
            break
        else:
            break
    return {"words": words, "assigns": assigns, "inner": inner, "shell_reads_input": shell_reads_input}


def shell_commands(src, depth=0):
    """Every simple command in `src` as {argv, assigns, redirects, heredocs}, with leading
    VAR=value assignments split out and wrappers peeled off, so `env X=1 git commit -n`
    reads as the git call it is."""
    out = []
    if depth > 4:
        return out
    peeled = []
    for c in _lex("" if src is None else str(src), 0, False)["cmds"]:
        merged = dict(c)
        merged.update(_peel(c["words"], depth))
        peeled.append(merged)
    # Text that reaches a shell as its script — `… | sh`, `sh <<EOF`, `sh <<< '…'`,
    # `bash <(echo …)`, `source <(…)` — is judged as commands too. Any word, heredoc or
    # here-string on the same line may be that text, so all of them are parsed.
    fed_to_shell = any(c["shell_reads_input"] for c in peeled)
    for c in peeled:
        words, assigns, redirects, heredocs = c["words"], c["assigns"], c["redirects"], c["heredocs"]
        if words or assigns or redirects:
            out.append({"argv": words, "assigns": assigns, "redirects": redirects, "heredocs": heredocs})
        out.extend(c["inner"])
        name = prog_name(words[0] if words else None)
        if words and name not in NON_EXEC and name not in SHELLS and name not in INTERPRETERS:
            # A wrapper we did not peel: find -exec, stdbuf, watch, npx, flock, script, parallel…
            at = next((k for k, w in enumerate(words) if k > 0 and prog_name(w) == "git"), -1)
            if at != -1:
                out.append({"argv": words[at:], "assigns": assigns, "redirects": [], "heredocs": []})
            for w in words[1:(len(words) if at == -1 else at)]:
                out.extend(_git_inside(w, depth))
        if fed_to_shell and depth < 4:
            texts = [*heredocs, *[r["target"] for r in redirects if r["op"] == "<<<"]]
            if len(words) > 1 and not c["shell_reads_input"]:
                texts.append(" ".join(words[1:]))
            for text in texts:
                out.extend(shell_commands(text, depth + 1))
    return out


# Builtins git never lets an alias shadow, so naming one needs no alias lookup.
GIT_BUILTINS = set(("add am annotate apply archive bisect blame branch bundle cat-file check-ignore "
                    "checkout cherry cherry-pick clean clone commit config describe diff difftool fetch for-each-ref "
                    "format-patch fsck gc grep help init log ls-files ls-remote ls-tree merge merge-base mergetool mv "
                    "notes pull push range-diff rebase reflog remote repack replace reset restore rev-list rev-parse "
                    "revert rm shortlog show show-ref sparse-checkout stash status submodule switch symbolic-ref tag "
                    "update-index update-ref var version worktree").split(" "))

# Global options that take a separate value when written without `=`.
GIT_GLOBAL_WITH_ARG = {"--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix", "--attr-source"}


def expand_home(p):
    """On Windows a Git Bash command names directories MSYS-style (`cd /c/Users/x/app`); abspath
    alone turns that into `C:\\c\\Users\\x\\app`, so the guard judged a directory that does not
    exist and the call went unchecked (issue #3 in 0.x). native_path is the one place that knows
    the spelling."""
    return native_path(p, sys.platform, os.path.expanduser("~"))


def _shell_quote(w):
    return "'" + w.replace("'", "'\\''") + "'"


def _alias_for(sub, config, dir_, locator):
    for entry in reversed(config):
        eq = entry.find("=")
        if eq != -1 and entry[:eq].lower() == "alias." + sub.lower():
            return entry[eq + 1:]
    try:
        return _git_out([*locator, "config", "--get", f"alias.{sub}"], dir_) or None
    except Exception:
        return None  # no such alias, or no repo


def command_walk(command, cwd=None):
    """Every simple command with the directory it runs in — after any earlier `cd`/`pushd`.
    A target the shell would compute (`cd $X`) leaves the directory unknown: `dir` None."""
    out = []
    dir_ = os.getcwd() if cwd is None else cwd
    for c in shell_commands(command):
        name = prog_name(c["argv"][0] if c["argv"] else None)
        if name == "cd" or name == "pushd":
            target = next((w for w in c["argv"][1:] if not w.startswith("-")), None)
            if target is None:
                dir_ = os.path.expanduser("~")
            elif UNKNOWN in target or dir_ is None:
                dir_ = None
            elif target != "-":
                dir_ = os.path.abspath(os.path.join(dir_, expand_home(target)))
        merged = dict(c)
        merged["dir"] = dir_
        out.append(merged)
    return out


def git_invocations(command, cwd=None):
    """Every git invocation `command` would run, as
    {sub, args, config, env, dir, locator, unknown}:
      sub/args  — the subcommand and what follows it, aliases resolved;
      config    — every `-c key=value` / `--config-env key=…` given before it;
      env       — VAR=value prefixes and earlier `export`s in the same command line;
      dir       — the directory git runs in (after any `cd` and its own `-C`s), or None;
      locator   — its --git-dir/--work-tree/--namespace options, to re-run git as it would;
      unknown   — the program or subcommand is something the shell computes ($GIT, $(…)).
    Global options before the subcommand are skipped the way git skips them, so
    `git -C . commit -n` and `git -c x=y --no-pager commit -n` are both a commit with -n."""
    found = []
    exported = {}

    def visit(argv, assigns, dir_, depth):
        name = prog_name(argv[0] if argv else None)
        if name == "export":
            for w in argv[1:]:
                eq = w.find("=")
                if eq > 0:
                    exported[w[:eq]] = w[eq + 1:]
            return
        # A program word the shell computes ($GIT, git${IFS}commit${IFS}-n) on a line that names
        # a commit or push: what runs cannot be known, so it is judged as unknowable.
        computed = UNKNOWN in name and re.search(r"commit|push", " ".join(argv)) is not None
        if (name != "git" and not computed) or depth > 4:
            return
        config = []
        locator = []
        at = dir_
        j = 1
        while j < len(argv) and argv[j].startswith("-"):
            tok = argv[j]
            eq = tok.find("=")
            opt = tok if eq == -1 else tok[:eq]
            if tok == "-C" or (tok.startswith("-C") and not tok.startswith("-C=")):
                target = (argv[j + 1] if j + 1 < len(argv) else ".") if tok == "-C" else tok[2:]
                at = None if (at is None or UNKNOWN in target) else os.path.abspath(os.path.join(at, expand_home(target)))
                j += 2 if tok == "-C" else 1
            elif tok == "-c":
                config.append(argv[j + 1] if j + 1 < len(argv) else "")
                j += 2
            elif tok.startswith("-c"):
                config.append(tok[2:])  # -ckey=value
                j += 1
            elif opt in GIT_GLOBAL_WITH_ARG:
                value = ((argv[j + 1] if j + 1 < len(argv) else "") if eq == -1 else tok[eq + 1:])
                if opt == "--config-env":
                    config.append(value)
                elif opt != "--super-prefix" and opt != "--attr-source":
                    locator.append(f"{opt}={value}")
                j += 2 if eq == -1 else 1
            else:
                j += 1
        env = {**exported, **assigns}
        if computed:
            sub = next((w for w in argv if w == "commit" or w == "push"), None)
            # argv.indexOf(undefined) is -1, so a computed program with no literal commit/push
            # word keeps the whole argv as its arguments.
            args = argv[(argv.index(sub) + 1 if sub in argv else 0):]
        else:
            sub = argv[j] if j < len(argv) else None
            args = argv[j + 1:]
        hops = 0
        while sub and UNKNOWN not in sub and sub not in GIT_BUILTINS and at is not None and hops < 5:
            alias = _alias_for(sub, config, at, locator)
            if not alias:
                break
            if alias.startswith("!"):
                # A shell alias: git runs it with the arguments appended.
                for c in command_walk(" ".join([alias[1:], *[_shell_quote(a) for a in args]]), cwd=at):
                    visit(c["argv"], {**env, **c["assigns"]}, c["dir"], depth + 1)
                sub = None
                break
            first = _lex(alias, 0, False)["cmds"]
            words = first[0]["words"] if first else []
            sub = words[0] if words else None
            args = [*words[1:], *args]
            hops += 1
        found.append({
            "sub": sub if sub is not None else None, "args": args, "config": config, "env": env, "dir": at,
            "locator": locator, "unknown": computed or bool(sub and UNKNOWN in sub),
        })

    for c in command_walk(command, cwd=cwd):
        visit(c["argv"], c["assigns"], c["dir"], 0)
    return found


def parse_options(args, short_with_arg="", short_optional_arg="", long_with_arg=()):
    """git's parse-options grammar, enough to tell a flag from a value: short clusters
    (-anm "msg" is -a -n -m "msg"; -mn is -m "n"), attached and separate values,
    --long=value, unambiguous --long prefixes, and `--` ending the options.
    Returns (opts, positionals): opts is a list of (name, value) with value None when there is
    none, which is also what an option missing its separate value gets."""
    opts = []
    positionals = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            positionals.extend(args[i + 1:])
            break
        if a.startswith("--"):
            eq = a.find("=")
            name = a if eq == -1 else a[:eq]
            takes = name in long_with_arg or (len(name) >= 5 and len([x for x in long_with_arg if x.startswith(name)]) == 1)
            if eq != -1:
                opts.append((name, a[eq + 1:]))
            elif takes:
                i += 1
                opts.append((name, args[i] if i < len(args) else None))
            else:
                opts.append((name, None))
        elif a.startswith("-") and len(a) > 1:
            for k in range(1, len(a)):
                ch = a[k]
                rest = a[k + 1:]
                if ch in short_with_arg:
                    if rest != "":
                        opts.append((f"-{ch}", rest))
                    else:
                        i += 1
                        opts.append((f"-{ch}", args[i] if i < len(args) else None))
                    break
                if ch in short_optional_arg:
                    opts.append((f"-{ch}", rest))
                    break
                opts.append((f"-{ch}", None))
        else:
            positionals.append(a)
        i += 1
    return opts, positionals


def is_long(name, full, min_length=5):
    """Long option `name` as typed matches `full` exactly or as git's unambiguous prefix."""
    return name == full or (len(name) >= min_length and full.startswith(name))


COMMIT_GRAMMAR = {
    "short_with_arg": "mFCct",
    "short_optional_arg": "Su",
    "long_with_arg": ["--message", "--file", "--reuse-message", "--reedit-message", "--fixup", "--squash",
                      "--author", "--date", "--template", "--cleanup", "--trailer", "--pathspec-from-file"],
}


def commit_message(inv):
    """The message a `git commit` invocation would use, or None when it can't be known
    without running something: no -m/-F (an editor or --no-edit), or a message built
    by a command substitution other than a bare `cat <<EOF` heredoc, or by a $VAR."""
    parts = []
    opts, _positionals = parse_options(inv["args"], **COMMIT_GRAMMAR)
    for name, value in opts:
        if name == "-m" or is_long(name, "--message"):
            parts.append(value if value is not None else "")
        elif name == "-F" or is_long(name, "--file"):
            if not value or value == "-" or inv["dir"] is None:
                return None
            try:
                with open(os.path.abspath(os.path.join(inv["dir"], value)), "rb") as f:
                    parts.append(f.read().decode("utf-8", errors="replace").rstrip("\n"))
            except Exception:
                return None
    if not parts:
        return None
    message = "\n\n".join(parts)
    return None if UNKNOWN in message else message
