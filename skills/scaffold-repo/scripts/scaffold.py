#!/usr/bin/env python3
"""scaffold.py — the bookkeeping half of the scaffold-repo skill: create a code repo from the
locked playbook's scaffold manifest, record every step, and refuse to destroy anything a person
changed.

Run from the plugin (never vendored into a workbench: it runs once, at G5, and needs the plugin's
templates), with `--workbench <path>` naming the workbench whose `adr/` holds the locked manifest
and `--dir <path>` (default: the current directory) the empty repo directory.

  scaffold.py plan   --workbench W [--packages api,web] [--choose api=go] [--monorepo] [--set k=v]...
  scaffold.py init   (same flags) --approved-by NAME     record the approved proposal; git init
  scaffold.py generate <package>        run the generator, render its files, run its `after`
  scaffold.py render <rules|git-hooks|ci|claude-md>     write one group of files
  scaffold.py commands                  write .rebuild/commands.json from the proposal
  scaffold.py contract                  every package has all five commands; are the tools there?
  scaffold.py run-commands              install, then build/lint/typecheck/test per package
  scaffold.py install-hooks             put the git hook shims in .git/hooks
  scaffold.py commit <step>             `chore(scaffold): <step>` for everything staged and new
  scaffold.py step-done <step>          record a step the skill did by hand
  scaffold.py status [--drift]          where setup stands; with --drift, vs the installed plugin
  scaffold.py finalize                  move the lock to .rebuild/ and mark setup complete

Every command prints JSON; exit 1 is an error, exit 2 is a refusal (a file someone edited).

WHY IT IS A SCRIPT AND NOT PROSE IN THE SKILL. A scaffold that is only instructions is redone from
memory each time, and the failure is not a crash: it is a repo whose `lint` command is a TODO, so
the pre-commit hook runs nothing and nobody notices. The script makes the five commands a
checked contract, runs them on day one, and records each exit, so "the skeleton passes" is a fact
in the lock and not a sentence in a summary. The skill keeps what needs judgement: the interview,
and deciding what to do when a generator or a tool is missing.

WHY THE LOCK LIVES IN .git/ UNTIL THE SKELETON EXISTS. Official generators (create-next-app, nuxi,
flutter create) refuse or prompt on a non-empty directory, and a `.rebuild/` folder is not on any
of their ignore lists. So state is kept in `.git/rebuild-scaffold.lock.json` while generators run,
and `finalize` moves it to `.rebuild/scaffold.lock.json`, where it is committed and where
`status --drift` reads it from then on.

FILE OWNERSHIP. Every file this writes is recorded with a class: `generated` (rewritten freely),
`seeded` (rewritten only while its hash still matches what was written; otherwise refused with a
diff), `vendored` (copied from the plugin, same rule as seeded) and `user` (written once, never
touched again). Plugin-owned files are named `rebuild-*` or live under `scripts/` as listed here;
everything else belongs to the project.
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TEMPLATES = os.path.join(HERE, "..", "templates")
sys.path.insert(0, os.path.join(PLUGIN, "skills", "rebuild-pipeline", "scripts"))
import playbook  # noqa: E402  (reads the manifest and validates it: what Gate 3 accepted is what runs)

STEPS_AFTER_SKELETON = ["commands", "run-commands", "rules", "git-hooks", "ci", "claude-md", "finalize"]
LOCK_WORKING = os.path.join(".git", "rebuild-scaffold.lock.json")
LOCK_FINAL = os.path.join(".rebuild", "scaffold.lock.json")
COMMANDS_FILE = os.path.join(".rebuild", "commands.json")
HOOK_MARKER = "# rebuild hook shim"


class Refused(Exception):
    pass


def out(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def die(msg: str, code: int = 1):
    print(f"scaffold: {msg}", file=sys.stderr)
    sys.exit(code)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


def write_bytes(path: str, data: bytes, mode: int | None = None) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    if mode is not None:
        os.chmod(path, mode)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plugin_version() -> str:
    try:
        with open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return json.load(f).get("version", "unknown")
    except OSError:
        return "unknown"


# --- the lock --------------------------------------------------------------------------------------

def lock_path(root: str) -> str:
    final = os.path.join(root, LOCK_FINAL)
    return final if os.path.exists(final) else os.path.join(root, LOCK_WORKING)


def load_lock(root: str, required: bool = True):
    p = lock_path(root)
    if not os.path.exists(p):
        if required:
            die("no scaffold lock here. Run `plan`, get the proposal approved, then `init` (from the repo directory, or pass --dir).")
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_lock(root: str, lock: dict) -> None:
    write_bytes(lock_path(root), (json.dumps(lock, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def step_done(lock: dict, step: str) -> None:
    lock.setdefault("steps", {})[step] = {"at": now()}


def all_steps(lock: dict) -> list[str]:
    return [f"skeleton:{p['name']}" for p in lock["proposal"]["packages"]] + STEPS_AFTER_SKELETON


# --- the manifest and the proposal -----------------------------------------------------------------

def resolve_manifest(workbench: str):
    """(manifest, manifest_path, playbook_name, templates_root) from the workbench's locked adr/."""
    adr = os.path.join(workbench, "adr")
    # The same fence the guards and upgrade.py apply: a workbench no 1.x release made carries a
    # playbook with no manifest, and the honest answer is that 1.x does not scaffold for it.
    try:
        with open(os.path.join(workbench, "locks", "pipeline.yaml"), encoding="utf-8") as f:
            made_by_1x = re.search(r"^rebuild_major:\s*[1-9]", f.read(), re.M) is not None
    except OSError:
        made_by_1x = False
    if not made_by_1x:
        die(f"{workbench} was not made by a 1.x release (locks/pipeline.yaml has no `rebuild_major`). 1.x does not scaffold for "
            f"a 0.x workbench: finish it on the 0.x line.")
    vendored = os.path.join(workbench, playbook.VENDORED_SCAFFOLD)
    local = os.path.join(workbench, playbook.SCAFFOLD_LOCAL)
    path = vendored if os.path.exists(vendored) else local
    if not os.path.exists(path):
        die(f"no scaffold manifest in {adr}: expected {playbook.VENDORED_SCAFFOLD} (vendored with the playbook at G4a) or "
            f"{playbook.SCAFFOLD_LOCAL}. Gate 3 should not have locked without one.")
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as e:
        die(f"{path} is not readable JSON ({e})")
    problems = playbook.scaffold_problems(manifest)
    if problems:
        die(f"{path} has problems Gate 3 should have caught:\n  " + "\n  ".join(problems))
    name = None
    pb = os.path.join(workbench, playbook.VENDORED_PLAYBOOK)
    if os.path.exists(pb):
        meta = playbook.parse_playbook_meta(read_text(pb))
        name = meta and meta.get("playbook")
    roots = [os.path.join(adr, "playbook-templates")]
    if name:
        roots.append(os.path.join(PLUGIN, "skills", "rebuild-pipeline", "references", "playbooks", name, "templates"))
    templates_root = next((r for r in roots if os.path.isdir(r)), None)
    return manifest, path, name, templates_root


def fill_cmd(text: str, values: dict, where: str) -> str:
    """{{key}} in commands and paths. An unknown key is an error: a command with a hole in it must not run."""
    def sub(m):
        k = m.group(1)
        if k not in values:
            die(f"{where}: {{{{{k}}}}} has no value (known: {', '.join(sorted(values))})")
        return str(values[k])
    return re.sub(r"\{\{\s*([\w-]+)\s*\}\}", sub, text)


def fill_content(text: str, values: dict) -> str:
    """[[key]] in file contents, for known keys only; anything else (a TOML [[table]]) is left alone."""
    return re.sub(r"\[\[\s*([\w-]+)\s*\]\]", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def parse_kv(items: list[str] | None, what: str) -> dict:
    result = {}
    for item in items or []:
        for pair in item.split(","):
            if not pair.strip():
                continue
            if "=" not in pair:
                die(f"{what}: expected key=value, got '{pair}'")
            k, v = pair.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def build_proposal(args, root: str) -> dict:
    manifest, mpath, pb_name, troot = resolve_manifest(args.workbench)
    asks = manifest.get("ask", [])
    given = parse_kv(args.set, "--set")
    missing = [a for a in asks if a["key"] not in given]
    if missing:
        die("values still needed (ask the user, with the suggestion):\n  " + "\n  ".join(
            f"--set {a['key']}=<value>   {a['prompt']}" + (f"   (suggest: {a['suggest']})" if a.get("suggest") else "") for a in missing))
    unknown = [k for k in given if k not in {a["key"] for a in asks}]
    if unknown:
        die(f"--set names keys the manifest does not ask for: {', '.join(unknown)}")
    chosen = parse_kv(args.choose, "--choose")
    wanted = [n.strip() for n in args.packages.split(",")] if args.packages else [p["name"] for p in manifest["packages"]]
    by_name = {p["name"]: p for p in manifest["packages"]}
    for n in wanted:
        if n not in by_name:
            die(f"no package '{n}' in the manifest (has: {', '.join(by_name)})")
    repo_name = os.path.basename(os.path.abspath(root))
    pkgs, seen_paths = [], {}
    for n in wanted:
        spec = by_name[n]
        options = spec["options"]
        opt = chosen.get(n) or (next(iter(options)) if len(options) == 1 else None)
        if opt is None:
            die(f"package '{n}' has {len(options)} options ({', '.join(options)}): choose one with --choose {n}=<option>, "
                f"from the stack the locked ADR decided. Do not decide it here.")
        if opt not in options:
            die(f"package '{n}' has no option '{opt}' (has: {', '.join(options)})")
        path = (spec.get("monorepoPath") or f"apps/{n}") if args.monorepo else spec.get("path", ".")
        path = path.replace("\\", "/").strip("/") or "."
        if path in seen_paths:
            die(f"packages '{seen_paths[path]}' and '{n}' would both live at '{path}'. One repo per package (polyrepo) means "
                f"scaffolding them one at a time with --packages; to put both in this repo, pass --monorepo.")
        seen_paths[path] = n
        o = options[opt]
        values = {**given, "name": n, "path": path, "repo": repo_name, "subpath": "" if path == "." else "/" + path}
        where = f"package {n} ({opt})"
        pkgs.append({
            "name": n, "option": opt, "path": path,
            "generator": [fill_cmd(c, values, f"{where} generator") for c in o.get("generator", [])],
            "after": [fill_cmd(c, values, f"{where} after") for c in o.get("after", [])],
            "files": [{"to": fill_cmd(f["to"], values, f"{where} files"), "class": f["class"],
                       **({"from": f["from"]} if "from" in f else {"content": fill_content(f["content"], values)})}
                      for f in o.get("files", [])],
            "commands": {k: (None if v is None else fill_cmd(v, values, f"{where} commands.{k}")) for k, v in o["commands"].items()},
            "ci": o.get("ci", {"setup": "none"}),
        })
        for f in pkgs[-1]["files"]:
            if "from" in f:
                if not troot or not os.path.isfile(os.path.join(troot, f["from"])):
                    die(f"{where}: template '{f['from']}' not found under {troot or '(no templates directory for this playbook)'}")
    return {
        "playbook": pb_name, "manifest": os.path.relpath(mpath, args.workbench).replace("\\", "/"),
        "manifest_sha256": sha(open(mpath, "rb").read()), "layout": "monorepo" if args.monorepo else "polyrepo",
        "values": given, "repo": repo_name, "packages": pkgs,
        "rules": manifest.get("rules", list(playbook.RULE_SEEDS)),
        "ci": {"os": (manifest.get("ci") or {}).get("os", ["ubuntu-latest"])},
        "templates_root": troot,
    }


# --- writing tracked files -------------------------------------------------------------------------

def write_tracked(root: str, lock: dict, rel: str, data: bytes, cls: str, mode: int | None = None) -> str:
    """Write `rel` under the ownership rules; returns 'created' | 'updated' | 'kept' | 'same'. Raises Refused."""
    rel = rel.replace("\\", "/")
    path = os.path.join(root, rel)
    files = lock.setdefault("files", {})
    entry = files.get(rel)
    if os.path.exists(path):
        current = open(path, "rb").read()
        if current == data:
            files[rel] = {"class": cls, "sha256": sha(data)}
            return "same"
        if cls == "user":
            return "kept"
        if cls != "generated":
            if entry is None or entry["sha256"] != sha(current):
                diff = "".join(difflib.unified_diff(current.decode("utf-8", "replace").splitlines(True),
                                                    data.decode("utf-8", "replace").splitlines(True),
                                                    f"{rel} (on disk)", f"{rel} (would write)"))
                raise Refused(f"{rel} {'was not written by this scaffold' if entry is None else 'has been edited since it was written'}; "
                              f"not overwriting.\n{diff[:3000]}")
        write_bytes(path, data, mode)
        files[rel] = {"class": cls, "sha256": sha(data)}
        return "updated"
    write_bytes(path, data, mode)
    files[rel] = {"class": cls, "sha256": sha(data)}
    return "created"


def tracked_group(root: str, lock: dict, items: list[tuple]) -> dict:
    result, refused = {}, []
    for rel, data, cls, mode in items:
        try:
            result[rel] = write_tracked(root, lock, rel, data, cls, mode)
        except Refused as e:
            refused.append(str(e))
    if refused:
        save_lock(root, lock)
        print("\n\n".join(refused), file=sys.stderr)
        out({"ok": False, "refused": len(refused), "written": result})
        sys.exit(2)
    return result


# --- commands --------------------------------------------------------------------------------------

def common_flags(p) -> None:
    p.add_argument("--workbench", help="the workbench whose adr/ holds the locked scaffold manifest")
    p.add_argument("--dir", default=".", help="the repo directory (default: current directory)")
    p.add_argument("--packages")
    p.add_argument("--choose", action="append")
    p.add_argument("--monorepo", action="store_true")
    p.add_argument("--set", action="append")


def git(root: str, *a: str, check: bool = True) -> subprocess.CompletedProcess:
    # GIT_* is dropped for the same reason the guards drop it: a command under judgement must not
    # steer the git the scaffold runs.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    r = subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, encoding="utf-8", env=env)
    if check and r.returncode != 0:
        die(f"git {' '.join(a)} failed: {(r.stderr or r.stdout).strip()}")
    return r


def cmd_plan(args) -> None:
    if not args.workbench:
        die("--workbench is required")
    root = os.path.abspath(args.dir)
    proposal = build_proposal(args, root)
    out({"proposal": {k: v for k, v in proposal.items() if k != "templates_root"}, "dir": root})


def cmd_init(args) -> None:
    if not args.workbench:
        die("--workbench is required")
    if not args.approved_by:
        die("--approved-by NAME is required: init records who approved this proposal, and nothing is generated before they do.")
    root = os.path.abspath(args.dir)
    os.makedirs(root, exist_ok=True)
    if load_lock(root, required=False):
        die("this directory already has a scaffold lock. To resume, run `status`; to start over, delete the directory.")
    leftovers = [e for e in os.listdir(root) if e not in (".git",)]
    if leftovers:
        die(f"{root} is not empty ({', '.join(sorted(leftovers)[:5])}). Generators refuse a non-empty directory; scaffold into an empty one, then add the workbench submodule.")
    proposal = build_proposal(args, root)
    if not os.path.isdir(os.path.join(root, ".git")):
        if git(root, "init", "-q", "-b", "main", check=False).returncode != 0:
            git(root, "init", "-q")
            git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    lock = {"scaffold_version": 1, "plugin_version": plugin_version(), "approved_by": args.approved_by,
            "approved_at": now(), "workbench_rel": os.path.relpath(os.path.realpath(args.workbench), os.path.realpath(root)).replace("\\", "/"),
            "proposal": {k: v for k, v in proposal.items() if k != "templates_root"},
            "templates_root": proposal["templates_root"], "steps": {}, "files": {}, "runs": []}
    step_done(lock, "init")
    save_lock(root, lock)
    out({"ok": True, "next": all_steps(lock)[0], "steps": all_steps(lock)})


def package(lock: dict, name: str) -> dict:
    for p in lock["proposal"]["packages"]:
        if p["name"] == name:
            return p
    die(f"no package '{name}' in the proposal (has: {', '.join(p['name'] for p in lock['proposal']['packages'])})")


def run_shell(cmd: str, cwd: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    # A shell line, deliberately: generators and the manifest's commands are written as one.
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def file_items(root: str, lock: dict, pkg: dict) -> list[tuple]:
    items = []
    for f in pkg["files"]:
        if "from" in f:
            data = open(os.path.join(lock["templates_root"], f["from"]), "rb").read()
            text = fill_content(data.decode("utf-8"), {**lock["proposal"]["values"], "name": pkg["name"], "path": pkg["path"], "repo": lock["proposal"]["repo"], "subpath": "" if pkg["path"] == "." else "/" + pkg["path"]})
        else:
            text = f["content"]
        rel = f["to"] if pkg["path"] == "." else f"{pkg['path']}/{f['to']}"
        items.append((rel, text.encode("utf-8"), f["class"], None))
    return items


def cmd_generate(args) -> None:
    root = os.path.abspath(args.dir)
    lock = load_lock(root)
    pkg = package(lock, args.package)
    base = os.path.join(root, pkg["path"])
    os.makedirs(base, exist_ok=True)
    entries = [e for e in os.listdir(base) if e not in (".git",)]
    if entries and pkg["path"] != "." and not args.force:
        die(f"{pkg['path']} already has files ({', '.join(sorted(entries)[:5])}); generators refuse a non-empty directory. "
            f"If a previous run died partway, delete it and rerun, or pass --force to run on top.")
    log = []
    for cmd in pkg["generator"]:
        r = run_shell(cmd, base)
        log.append({"cmd": cmd, "exit": r.returncode})
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-3000:], file=sys.stderr)
            lock["runs"].append({"step": f"skeleton:{pkg['name']}", "phase": "generator", **log[-1], "at": now()})
            save_lock(root, lock)
            die(f"generator failed ({cmd!r}, exit {r.returncode}). The skeleton is not recorded as done; fix the cause and rerun `generate {pkg['name']} --force`.")
    written = tracked_group(root, lock, file_items(root, lock, pkg))
    for cmd in pkg["after"]:
        r = run_shell(cmd, base)
        log.append({"cmd": cmd, "exit": r.returncode})
        if r.returncode != 0:
            print((r.stdout + r.stderr)[-3000:], file=sys.stderr)
            lock["runs"].append({"step": f"skeleton:{pkg['name']}", "phase": "after", **log[-1], "at": now()})
            save_lock(root, lock)
            die(f"after-step failed ({cmd!r}, exit {r.returncode}).")
    lock["runs"].extend({"step": f"skeleton:{pkg['name']}", **l, "at": now()} for l in log)
    step_done(lock, f"skeleton:{pkg['name']}")
    save_lock(root, lock)
    out({"ok": True, "package": pkg["name"], "path": pkg["path"], "files": written, "ran": log})


def globs(lock: dict) -> dict:
    srcs = []
    for p in lock["proposal"]["packages"]:
        srcs.append("**" if p["path"] == "." else f"{p['path']}/**")
    yl = lambda items: "\n".join(f'  - "{i}"' for i in items)  # noqa: E731
    return {
        "source_globs": yl(srcs),
        "test_globs": yl(["**/tests/**", "**/test/**", "**/__tests__/**", "**/*_test.*", "**/*.test.*", "**/*.spec.*"]),
        "ci_globs": yl([".github/**", "scripts/**", "Dockerfile*", "docker-compose*"]),
        "migration_globs": yl(["**/migrations/**", "**/*.sql"]),
        "sensitive_globs": yl(["**/.env*", "**/secrets/**", "**/*.pem", "**/*.key"]),
    }


def template(*parts: str) -> str:
    return read_text(os.path.join(TEMPLATES, *parts))


def render_rules(root: str, lock: dict) -> dict:
    g = globs(lock)
    values = {"plugin_version": plugin_version(), "repo": lock["proposal"]["repo"], **g}
    paths_key = {"code-style": "source_globs", "tests": "test_globs", "migrations": "migration_globs",
                 "sensitive": "sensitive_globs", "ci": "ci_globs"}
    items = []
    for seed in lock["proposal"]["rules"]:
        text = fill_content(template("rules", f"{seed}.md"), {**values, "paths": g[paths_key[seed]]})
        items.append((f".claude/rules/rebuild-{seed}.md", text.encode("utf-8"), "generated", None))
    return tracked_group(root, lock, items)


def render_git_hooks(root: str, lock: dict) -> dict:
    items = [
        ("scripts/py.sh", open(os.path.join(PLUGIN, "hooks", "py.sh"), "rb").read(), "vendored", 0o755),
        ("scripts/commit_msg.py", open(os.path.join(PLUGIN, "hooks", "scripts", "commit_rules.py"), "rb").read(), "vendored", 0o755),
        ("scripts/pre-commit.sh", template("hooks", "pre-commit.sh").encode("utf-8"), "seeded", 0o755),
        ("scripts/rebuild_precommit.py", template("hooks", "rebuild_precommit.py").encode("utf-8"), "seeded", 0o755),
    ]
    written = tracked_group(root, lock, items)
    written["hooks"] = install_hooks(root)
    return written


SHIMS = {
    "pre-commit": f'#!/bin/sh\n{HOOK_MARKER}: runs the tracked script, so it never goes stale\nexec sh "$(git rev-parse --show-toplevel)/scripts/pre-commit.sh" "$@"\n',
    "commit-msg": f'#!/bin/sh\n{HOOK_MARKER}: runs the tracked script, so it never goes stale\nexec bash "$(git rev-parse --show-toplevel)/scripts/py.sh" "$(git rev-parse --show-toplevel)/scripts/commit_msg.py" "$1"\n',
}


def install_hooks(root: str) -> dict:
    """Shims, not symlinks: a symlink needs Developer Mode on Windows, and a copy goes stale. A foreign
    hook (husky, a hand-written one) is never clobbered."""
    hooks_dir = os.path.join(root, ".git", "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    result = {}
    for name, body in SHIMS.items():
        p = os.path.join(hooks_dir, name)
        if os.path.exists(p) and HOOK_MARKER not in read_text(p):
            result[name] = "foreign hook left in place"
            continue
        write_bytes(p, body.encode("utf-8"), 0o755)
        result[name] = "installed"
    return result


SETUP_STEPS = {
    "go": lambda pkg: ["      - uses: actions/setup-go@v5", "        with:", f"          go-version-file: {pkg['path']}/go.mod"],
    "node": lambda pkg: ["      - uses: actions/setup-node@v4", "        with:", f"          node-version: \"{pkg['ci'].get('version', '22')}\""],
    "flutter": lambda pkg: ["      - uses: subosito/flutter-action@v2", "        with:", "          channel: stable"],
}


def render_ci(root: str, lock: dict) -> dict:
    prop = lock["proposal"]
    lines = ["# Written by the rebuild scaffold-repo skill from .rebuild/commands.json; every step is a command a person",
             "# runs locally, so CI and local work cannot drift. Add jobs; do not weaken a step to get green.",
             "name: verify", "on: [push, pull_request]", "jobs:"]
    for pkg in prop["packages"]:
        lines += [f"  {pkg['name']}:", "    runs-on: ${{ matrix.os }}", "    strategy:", "      matrix:",
                  f"        os: [{', '.join(prop['ci']['os'])}]", "    defaults:", "      run:",
                  f"        working-directory: {pkg['path']}", "    steps:", "      - uses: actions/checkout@v4"]
        setup = pkg["ci"].get("setup", "none")
        if setup in SETUP_STEPS:
            lines += SETUP_STEPS[setup](pkg)
        elif setup == "none":
            lines.append("      # TODO: no toolchain setup action is known for this stack; add one.")
        for pre in pkg["ci"].get("pre", []):
            lines.append(f"      - run: {pre}")
        for key in ("install", "build", "lint", "typecheck", "test"):
            if pkg["commands"].get(key):
                lines.append(f"      - run: {pkg['commands'][key]}")
    data = ("\n".join(lines) + "\n").encode("utf-8")
    return tracked_group(root, lock, [(".github/workflows/rebuild-verify.yml", data, "seeded", None)])


def render_claude_md(root: str, lock: dict) -> dict:
    text = fill_content(template("claude-md.md"), {"repo": lock["proposal"]["repo"], "workbench": lock.get("workbench_rel", "<the rebuild workbench>")})
    return tracked_group(root, lock, [("CLAUDE.md", text.encode("utf-8"), "user", None)])


def cmd_render(args) -> None:
    root = os.path.abspath(args.dir)
    lock = load_lock(root)
    if args.step == "files":
        written = {}
        for pkg in lock["proposal"]["packages"]:
            written.update(tracked_group(root, lock, file_items(root, lock, pkg)))
    else:
        written = {"rules": render_rules, "git-hooks": render_git_hooks, "ci": render_ci, "claude-md": render_claude_md}[args.step](root, lock)
        if args.step in ("rules", "git-hooks", "ci", "claude-md"):
            step_done(lock, args.step)
    save_lock(root, lock)
    out({"ok": True, "step": args.step, "files": written})


def commands_doc(lock: dict) -> dict:
    return {"packages": [{"name": p["name"], "path": p["path"], "stack": p["option"], "commands": p["commands"]}
                         for p in lock["proposal"]["packages"]]}


def cmd_commands(args) -> None:
    root = os.path.abspath(args.dir)
    lock = load_lock(root)
    data = (json.dumps(commands_doc(lock), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    result = tracked_group(root, lock, [(COMMANDS_FILE.replace("\\", "/"), data, "generated", None)])
    step_done(lock, "commands")
    save_lock(root, lock)
    out({"ok": True, "file": COMMANDS_FILE, "written": result})


def executable_of(cmd: str) -> str:
    return re.split(r"\s+", cmd.strip())[0] if cmd and cmd.strip() else ""


def cmd_contract(args) -> None:
    root = os.path.abspath(args.dir)
    p = os.path.join(root, COMMANDS_FILE)
    if not os.path.exists(p):
        die(f"{COMMANDS_FILE} does not exist; run `commands` first.")
    doc = json.load(open(p, encoding="utf-8"))
    problems, missing_tools = [], []
    for pkg in doc.get("packages", []):
        for k in playbook.COMMAND_KEYS:
            if k not in pkg["commands"]:
                problems.append(f"{pkg['name']}: commands.{k} is missing (write the command, or null where the stack has no such step)")
        for k, cmd in pkg["commands"].items():
            exe = executable_of(cmd)
            # A shell line may start with a builtin or an env assignment; only a bare program name is checked.
            if exe and re.match(r"^[\w.+-]+$", exe) and "=" not in exe and exe not in ("cd", "echo", "exit", "set") and shutil.which(exe) is None:
                missing_tools.append({"package": pkg["name"], "command": k, "tool": exe})
    out({"ok": not problems, "tools_ok": not missing_tools, "problems": problems, "missing_tools": missing_tools,
         "note": "A missing tool is a user decision (installing anything is a hard stop): ask, or change the command in the manifest." if missing_tools else ""})
    sys.exit(0 if not problems and not missing_tools else 1)


def cmd_run_commands(args) -> None:
    root = os.path.abspath(args.dir)
    lock = load_lock(root)
    doc = json.load(open(os.path.join(root, COMMANDS_FILE), encoding="utf-8"))
    results, failed = [], False
    for pkg in doc["packages"]:
        cwd = os.path.join(root, pkg["path"])
        for key in ("install", "build", "lint", "typecheck", "test"):
            cmd = pkg["commands"].get(key)
            if not cmd:
                results.append({"package": pkg["name"], "command": key, "skipped": True})
                continue
            r = run_shell(cmd, cwd)
            row = {"package": pkg["name"], "command": key, "cmd": cmd, "exit": r.returncode}
            if r.returncode != 0:
                failed = True
                row["tail"] = (r.stdout + r.stderr)[-1500:]
            results.append(row)
            lock["runs"].append({"step": "run-commands", **{k: v for k, v in row.items() if k != "tail"}, "at": now()})
    ran = [r for r in results if not r.get("skipped")]
    ok = bool(ran) and not failed
    if ok:
        step_done(lock, "run-commands")
    save_lock(root, lock)
    out({"ok": ok, "results": results,
         "note": "" if ok else "Fix the skeleton, never the command: a command changed to pass is a skeleton that does not."})
    sys.exit(0 if ok else 1)


def cmd_commit(args) -> None:
    root = os.path.abspath(args.dir)
    git(root, "add", "-A")
    if not git(root, "status", "--porcelain").stdout.strip():
        out({"ok": True, "committed": False})
        return
    git(root, "-c", "user.name=" + (git(root, "config", "user.name", check=False).stdout.strip() or "scaffold"),
        "-c", "user.email=" + (git(root, "config", "user.email", check=False).stdout.strip() or "scaffold@localhost"),
        "commit", "-q", "-m", f"chore(scaffold): {args.step}")
    out({"ok": True, "committed": True, "subject": f"chore(scaffold): {args.step}"})


def cmd_step_done(args) -> None:
    root = os.path.abspath(args.dir)
    lock = load_lock(root)
    if args.step not in all_steps(lock) + ["init"]:
        die(f"unknown step '{args.step}' (steps: {', '.join(all_steps(lock))})")
    step_done(lock, args.step)
    save_lock(root, lock)
    out({"ok": True, "step": args.step})


def cmd_finalize(args) -> None:
    root = os.path.abspath(args.dir)
    lock = load_lock(root)
    pending = [s for s in all_steps(lock) if s != "finalize" and s not in lock["steps"]]
    if pending:
        die(f"not finished: {', '.join(pending)}")
    step_done(lock, "finalize")
    lock["complete"] = True
    working = os.path.join(root, LOCK_WORKING)
    final = os.path.join(root, LOCK_FINAL)
    write_bytes(final, (json.dumps(lock, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    if os.path.exists(working):
        os.remove(working)
    out({"ok": True, "lock": LOCK_FINAL})


def cmd_status(args) -> None:
    root = os.path.abspath(args.dir)
    lock = load_lock(root, required=False)
    if not lock:
        out({"setup": "none"})
        return
    steps = all_steps(lock)
    done = [s for s in steps if s in lock["steps"]]
    status = {"setup": "complete" if lock.get("complete") else "in_progress", "completed_steps": done,
              "next": next((s for s in steps if s not in lock["steps"]), None), "plugin_version": lock["plugin_version"],
              "approved_by": lock["approved_by"]}
    if args.drift:
        now_v = plugin_version()
        status["drift"] = "current" if now_v == lock["plugin_version"] else "differs"
        status["installed_plugin_version"] = now_v
        status["modified_files"] = [rel for rel, e in lock.get("files", {}).items()
                                    if os.path.exists(os.path.join(root, rel)) and sha(open(os.path.join(root, rel), "rb").read()) != e["sha256"]
                                    and e["class"] != "user"]
        status["note"] = "Report only: there is no applier. A rebuild repo lives for one project."
    out(status)


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="scaffold.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "init"):
        p = sub.add_parser(name)
        common_flags(p)
        if name == "init":
            p.add_argument("--approved-by")
    p = sub.add_parser("generate")
    p.add_argument("package")
    p.add_argument("--dir", default=".")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("render")
    p.add_argument("step", choices=["files", "rules", "git-hooks", "ci", "claude-md"])
    p.add_argument("--dir", default=".")
    for name in ("commands", "contract", "run-commands", "install-hooks", "finalize"):
        p = sub.add_parser(name)
        p.add_argument("--dir", default=".")
    p = sub.add_parser("commit")
    p.add_argument("step")
    p.add_argument("--dir", default=".")
    p = sub.add_parser("step-done")
    p.add_argument("step")
    p.add_argument("--dir", default=".")
    p = sub.add_parser("status")
    p.add_argument("--dir", default=".")
    p.add_argument("--drift", action="store_true")
    args = ap.parse_args(argv)
    handlers = {"plan": cmd_plan, "init": cmd_init, "generate": cmd_generate, "render": cmd_render, "commands": cmd_commands,
                "contract": cmd_contract, "run-commands": cmd_run_commands, "commit": cmd_commit, "step-done": cmd_step_done,
                "finalize": cmd_finalize, "status": cmd_status,
                "install-hooks": lambda a: out({"ok": True, "hooks": install_hooks(os.path.abspath(a.dir))})}
    try:
        handlers[args.cmd](args)
    except Refused as e:
        print(f"scaffold: refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
