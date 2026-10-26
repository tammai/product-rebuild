#!/bin/sh
# pre-commit — runs the fast checks recorded in .rebuild/commands.json, through the same Python
# launcher the plugin's own hooks use (scripts/py.sh), so it works where `python3` is not a name
# that exists (Windows). Installed as a shim in .git/hooks by `scaffold.py install-hooks`; the
# shim runs THIS tracked file, so an update never leaves a stale copy behind.
dir="$(cd "$(dirname "$0")" && pwd)"
exec bash "$dir/py.sh" "$dir/rebuild_precommit.py" "$@"
