#!/usr/bin/env python3
"""rebuild_precommit.py — the git pre-commit gate: lint, type-check and the fast tests for each
package that has staged changes, using the commands in sdlc's .sdlc/config.json.

WHY IT EXISTS BESIDE SDLC. sdlc installs no git hooks, and a commit a person makes outside a Claude
session meets no plugin hook at all; this is the one gate that still runs then.

WHY IT RUNS WHAT IT RUNS. A pre-commit hook that runs the whole test suite makes every commit a
wait, and the suite is exactly what the slice's cadence says to run once, at the joint run. In a
rebuild repo sdlc's `test` command is already the fast suite (the scaffold writes it that way), so
this runs `lint`, `typecheck` and `test` and nothing slower. Build belongs to CI.

WHY IT FAILS OPEN WITHOUT the config. The hook is installed by the scaffold before sdlc's setup has
run; a hook that blocks every commit of the skeleton itself would be disabled by hand on day one,
which is worse than a gate that opens until the commands exist.
Exit 1 blocks the commit.
"""
import json
import os
import subprocess
import sys


def packages(cfg):
    """sdlc's two shapes: `packages` (name, path, commands), or `commands` for the repo root."""
    if cfg.get("packages"):
        return [{"name": p.get("name", p.get("path", ".")), "path": p.get("path", "."), "commands": p.get("commands") or {}}
                for p in cfg["packages"]]
    return [{"name": "root", "path": ".", "commands": cfg.get("commands") or {}}]


def main() -> int:
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    path = os.path.join(root, ".sdlc", "config.json")
    if not os.path.exists(path):
        print("pre-commit: .sdlc/config.json not written yet, so nothing to run.")
        return 0
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=root, capture_output=True, text=True).stdout.split()
    for pkg in packages(cfg):
        prefix = "" if pkg["path"] in (".", "") else pkg["path"].rstrip("/") + "/"
        if not any(s.startswith(prefix) for s in staged):
            continue
        for key in ("lint", "typecheck", "test"):
            cmd = pkg["commands"].get(key)
            if not cmd:
                continue
            print(f"pre-commit [{pkg['name']}] {key}: {cmd}")
            if subprocess.run(cmd, cwd=os.path.join(root, pkg["path"]), shell=True).returncode != 0:
                print(f"pre-commit: {pkg['name']} {key} failed. Fix it; do not bypass the hook.", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
