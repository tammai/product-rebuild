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

for candidate in "python3" "python" "py -3"; do
    exe="${candidate%% *}"
    command -v "$exe" >/dev/null 2>&1 || continue
    # shellcheck disable=SC2086  # `py -3` is deliberately two words
    if probe $candidate; then
        # shellcheck disable=SC2086
        exec $candidate "$@"
    fi
done

echo "product-rebuild: no usable Python 3.9+ found (tried python3, python, py -3). Install Python 3.9 or newer; this plugin's guards and scripts need nothing else." >&2
exit 2
