#!/usr/bin/env bash
# py.sh — find a working Python 3 and run a hook script with it.
#
# WHY A SHIM AND NOT `python3 script.py` IN hooks.json. On Windows with Git Bash, `python3`
# usually resolves to the Microsoft Store stub, which exits 49 silently when run without a
# terminal; every hook would then fail and, for a blocking guard, a guard that did not run reads
# as a guard that passed. So this probes each candidate with a real call and skips one that
# cannot run. It also converts MSYS-style drive paths (`/c/Users/...`) to the native form a
# Windows python.exe understands, which it otherwise reads as `C:\c\Users\...` and fails on.
#
# Order: python3 (macOS, Linux), python (python.org installs on Windows), py -3 (Windows
# launcher). A candidate counts only if it is Python >= 3.9 AND can read the script it is about
# to run: Windows packaged-launcher aliases answer `-c` and then fail on the file.
#
# Adapted from the sdlc plugin's hooks/sg-python.sh (MIT, same author), cut to what this plugin
# needs; see NOTICE.md. Usage in hooks.json:
#   bash "${CLAUDE_PLUGIN_ROOT}/hooks/py.sh" "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/<guard>.py"
#
# FAILS CLOSED, deliberately: with no usable Python it prints why on stderr and exits 2, which
# blocks the tool call. A PostToolUse or SessionStart hook cannot block, so there it is a
# visible error instead of a silent skip.
set -e

# Python on Windows defaults to a legacy code page for stdin/stdout/file reads, which crashes on
# any non-ASCII path or message. Must be set before the interpreter starts.
export PYTHONUTF8=1

if command -v cygpath >/dev/null 2>&1; then
    converted=()
    for a in "$@"; do
        case "$a" in
            /*) converted+=("$(cygpath -w "$a")") ;;
            *)  converted+=("$a") ;;
        esac
    done
    set -- "${converted[@]}"
fi

target="${1:-}"

probe() {
    # Prints nothing and returns non-zero unless "$@" is Python >= 3.9 that can read $target.
    "$@" -c 'import os, sys
t = (sys.argv[1:] or [""])[0]
sys.exit(0 if sys.version_info >= (3, 9) and (not t or (os.path.isfile(t) and os.access(t, os.R_OK))) else 3)' "$target" >/dev/null 2>&1
}

# FAST PATH. The probe above starts a whole interpreter to check a version, and then `exec` starts a second
# one for the guard: about 35 ms of an 85 to 130 ms hook, on every tool call, for eight guards. The answer
# does not change within a session, so a successful probe is remembered, keyed by PATH, and the next run
# skips it. Never on Windows (cygpath exists there): the Store-stub failure that the probe is for is exactly
# the one a cached answer would hide. The cache holds only one of the three candidate strings below and only
# if the file is ours, so a file planted at a predictable path in a shared /tmp can name nothing else to run.
cache=""
if ! command -v cygpath >/dev/null 2>&1 && command -v cksum >/dev/null 2>&1; then
    cache="${TMPDIR:-/tmp}/product-rebuild-py-$(id -u 2>/dev/null || echo 0)-$(printf '%s' "$PATH" | cksum | cut -d' ' -f1)"
    if [ -O "$cache" ] && [ ! -L "$cache" ] && { [ -z "$target" ] || [ -r "$target" ]; }; then
        cached="$(cat "$cache" 2>/dev/null || true)"
        case "$cached" in
            "python3"|"python"|"py -3")
                if command -v "${cached%% *}" >/dev/null 2>&1; then
                    # shellcheck disable=SC2086
                    exec $cached "$@"
                fi
                ;;
        esac
    fi
fi

for candidate in "python3" "python" "py -3"; do
    exe="${candidate%% *}"
    command -v "$exe" >/dev/null 2>&1 || continue
    # shellcheck disable=SC2086  # `py -3` is deliberately two words
    if probe $candidate; then
        if [ -n "$cache" ]; then
            # Atomic, so two guards starting together cannot leave a half-written name behind.
            printf '%s' "$candidate" > "$cache.$$" 2>/dev/null && mv -f "$cache.$$" "$cache" 2>/dev/null || true
        fi
        # shellcheck disable=SC2086
        exec $candidate "$@"
    fi
done

echo "product-rebuild: no usable Python 3.9+ found (tried python3, python, py -3). Install Python 3.9 or newer; this plugin's guards and scripts need nothing else." >&2
exit 2
