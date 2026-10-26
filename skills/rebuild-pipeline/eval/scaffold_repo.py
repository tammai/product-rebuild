#!/usr/bin/env python3
"""scaffold_repo.py (eval) — E19: does scaffold.py keep the contract the scaffold-repo skill relies on?

  python3 skills/rebuild-pipeline/eval/scaffold_repo.py

WHY IT EXISTS. A scaffold fails quietly: the repo is created, the hook is installed, and the `lint`
command is a TODO, so nothing is ever checked. This runs the real scaffold.py end to end against a
manifest whose generators are stubs (a Python one-liner, so no network and no toolchain) and asserts
the things that fail silently: the five-command contract, every exit recorded, a file a person
edited never overwritten, a run that died resumable, and the git hooks actually blocking.

It also validates the two shipped manifests with the same function Gate 3 uses. What it does NOT do
is run the real generators (go, nuxi, create-next-app, flutter create): those need a network and
toolchains, and are exercised by the by-hand end-to-end run before release.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SCRIPTS = os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts")
SCAFFOLD = os.path.join(ROOT, "skills", "scaffold-repo", "scripts", "scaffold.py")
sys.path.insert(0, SCRIPTS)
import playbook  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


def sc(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, SCAFFOLD, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def js(r: subprocess.CompletedProcess):
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def git(cwd: str, *a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "user.name=Eval", "-c", "user.email=eval@x", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


PY = json.dumps(sys.executable)  # quoted: the interpreter's path may hold spaces
OK = f"{PY} -c \"import sys; sys.exit(0)\""
FAIL = f"{PY} -c \"import sys; sys.exit(3)\""
MAKE_FILE = f"{PY} -c \"open('generated.txt','w').write('from generator')\""
base = tempfile.mkdtemp(prefix="scaffold-repo-eval-")


def manifest(**over) -> dict:
    m = {
        "ask": [{"key": "org", "prompt": "Owner", "suggest": "acme"}],
        "rules": ["code-style", "tests", "ci"],
        "ci": {"os": ["ubuntu-latest"]},
        "packages": [{
            "name": "api", "path": ".", "monorepoPath": "apps/api",
            "options": {
                "go": {"generator": [MAKE_FILE], "after": [], "files": [
                    {"content": "seeded for [[org]] in [[repo]]\n", "to": "seeded.txt", "class": "seeded"},
                    {"content": "generated\n", "to": "gen.txt", "class": "generated"}],
                    "commands": {"install": OK, "build": OK, "lint": OK, "typecheck": None, "test": OK, "test_fast": OK},
                    "ci": {"setup": "none"}},
                "alt": {"generator": [], "files": [{"content": "x\n", "to": "x.txt", "class": "seeded"}],
                        "commands": {"install": OK, "build": None, "lint": OK, "typecheck": None, "test": OK}},
            }}],
    }
    m.update(over)
    return m


def workbench(name: str, m: dict) -> str:
    wb = os.path.join(base, name)
    os.makedirs(os.path.join(wb, "adr"))
    with open(os.path.join(wb, "adr", "scaffold.json"), "w") as f:
        json.dump(m, f)
    return wb


def fresh_repo(name: str) -> str:
    d = os.path.join(base, name)
    os.makedirs(d)
    return d


# --- the manifest contract (what Gate 3 accepts) -------------------------------------------------
print("# manifest contract")
for pb in ("web-modular-monolith", "mobile-flutter"):
    p = os.path.join(ROOT, "skills", "rebuild-pipeline", "references", "playbooks", pb, "scaffold.json")
    m = json.load(open(p))
    check(f"the shipped {pb} manifest passes the Gate 3 check", playbook.scaffold_problems(m) == [], str(playbook.scaffold_problems(m)))
    meta = playbook.parse_playbook_meta(open(os.path.join(os.path.dirname(p), "..", f"{pb}.md"), encoding="utf-8").read())
    check(f"{pb}'s frontmatter points at it", meta and meta["scaffold"] == f"{pb}/scaffold.json", str(meta and meta["scaffold"]))
    for pkg in m["packages"]:
        for opt, o in pkg["options"].items():
            for f in o.get("files", []):
                if "from" in f:
                    tp = os.path.join(os.path.dirname(p), "templates", f["from"])
                    check(f"{pb}/{pkg['name']}/{opt}: template {f['from']} exists", os.path.isfile(tp), tp)
good = manifest()
check("a valid manifest has no problems", playbook.scaffold_problems(good) == [])
broken = manifest(typo=1)
check("an unknown top-level key is named", any('unknown key "typo"' in p for p in playbook.scaffold_problems(broken)))
bad = manifest()
del bad["packages"][0]["options"]["go"]["commands"]["lint"]
check("a missing command is named (write it, or null)", any("commands.lint is missing" in p for p in playbook.scaffold_problems(bad)))
bad = manifest()
bad["packages"][0]["options"]["go"]["generator"] = ["echo {{nope}}"]
check("an unknown {{placeholder}} in a command is named", any("{{nope}}" in p for p in playbook.scaffold_problems(bad)))
bad = manifest(ask=[{"key": "name", "prompt": "x"}])
check("an ask key may not shadow a built-in", any("shadows a built-in" in p for p in playbook.scaffold_problems(bad)))
bad = manifest()
bad["packages"][0]["options"]["go"]["files"][0]["to"] = "../escape.txt"
check("a file may not leave the repo", any("stay inside the repo" in p for p in playbook.scaffold_problems(bad)))
check("[[placeholders]] in file content are not checked (a Go or Vue template is full of braces)",
      playbook.scaffold_problems(manifest()) == [])

wbdir = os.path.join(base, "nopb")
os.makedirs(os.path.join(wbdir, "adr"))
meta_none = {"scaffold": "none", "playbook": "x"}
check("`scaffold: none` fails the playbook check", bool(playbook.check_scaffold(wbdir, meta_none)["problems"]))
check("a playbook with no scaffold key fails it", bool(playbook.check_scaffold(wbdir, {"scaffold": None, "playbook": "x"})["problems"]))

# --- plan and init ---------------------------------------------------------------------------------
print("\n# plan and init")
wb = workbench("wb1", good)
repo = fresh_repo("repo1")
r = sc(repo, "plan", "--workbench", wb, "--packages", "api", "--choose", "api=go")
check("plan asks for every value the manifest asks for", r.returncode == 1 and "--set org=" in r.stderr and "suggest: acme" in r.stderr, r.stderr)
r = sc(repo, "plan", "--workbench", wb, "--set", "org=acme")
check("plan refuses to decide between options: the stack was decided at Gate 3", r.returncode == 1 and "choose one with --choose api=" in r.stderr, r.stderr)
r = sc(repo, "plan", "--workbench", wb, "--choose", "api=nope", "--set", "org=acme")
check("plan names an option that does not exist", r.returncode == 1 and "no option 'nope'" in r.stderr, r.stderr)
r = sc(repo, "plan", "--workbench", wb, "--choose", "api=go", "--set", "org=acme")
prop = (js(r) or {}).get("proposal", {})
check("plan prints the proposal without writing anything", r.returncode == 0 and prop.get("layout") == "polyrepo" and os.listdir(repo) == [], r.stderr)
r = sc(repo, "init", "--workbench", wb, "--choose", "api=go", "--set", "org=acme")
check("init refuses without --approved-by: nothing is generated before a person approves", r.returncode == 1 and "--approved-by" in r.stderr, r.stderr)
with open(os.path.join(repo, "stray.txt"), "w") as f:
    f.write("x")
r = sc(repo, "init", "--workbench", wb, "--choose", "api=go", "--set", "org=acme", "--approved-by", "Eval")
check("init refuses a non-empty directory", r.returncode == 1 and "is not empty" in r.stderr, r.stderr)
os.remove(os.path.join(repo, "stray.txt"))
r = sc(repo, "init", "--workbench", wb, "--choose", "api=go", "--set", "org=acme", "--approved-by", "Eval")
check("init records the approval and starts a git repo", r.returncode == 0 and os.path.isdir(os.path.join(repo, ".git")) and
      os.path.exists(os.path.join(repo, ".git", "rebuild-scaffold.lock.json")), r.stderr)
check("…keeping the lock in .git/ until the skeleton exists (generators refuse a .rebuild/ folder)", not os.path.exists(os.path.join(repo, ".rebuild")))
r = sc(repo, "init", "--workbench", wb, "--choose", "api=go", "--set", "org=acme", "--approved-by", "Eval")
check("a second init is refused", r.returncode == 1 and "already has a scaffold lock" in r.stderr, r.stderr)

# --- generate, commands, contract, run-commands -------------------------------------------------
print("\n# generate, contract, run")
r = sc(repo, "generate", "api")
d = js(r) or {}
check("generate runs the generator and renders the files", r.returncode == 0 and os.path.exists(os.path.join(repo, "generated.txt")) and
      d.get("files", {}).get("seeded.txt") == "created", r.stderr + r.stdout)
check("[[org]] and [[repo]] are substituted in file content", open(os.path.join(repo, "seeded.txt")).read() == "seeded for acme in repo1\n")
check("the skeleton step is recorded", "skeleton:api" in json.load(open(os.path.join(repo, ".git", "rebuild-scaffold.lock.json")))["steps"])
r = sc(repo, "commands")
check("commands writes .rebuild/commands.json", r.returncode == 0 and os.path.exists(os.path.join(repo, ".rebuild", "commands.json")), r.stderr)
r = sc(repo, "contract")
check("contract passes for five commands (null counts)", r.returncode == 0 and (js(r) or {}).get("ok") is True, r.stdout + r.stderr)
cj = os.path.join(repo, ".rebuild", "commands.json")
orig = open(cj).read()
doc = json.loads(orig)
del doc["packages"][0]["commands"]["lint"]
open(cj, "w").write(json.dumps(doc))
r = sc(repo, "contract")
check("contract fails when a command is missing", r.returncode == 1 and "commands.lint is missing" in r.stdout, r.stdout)
doc = json.loads(orig)
doc["packages"][0]["commands"]["lint"] = "definitely-not-a-real-tool-xyz --check"
open(cj, "w").write(json.dumps(doc))
r = sc(repo, "contract")
check("contract names a tool that is not installed, as a user decision", r.returncode == 1 and (js(r) or {}).get("tools_ok") is False and
      "definitely-not-a-real-tool-xyz" in r.stdout, r.stdout)
open(cj, "w").write(orig)
r = sc(repo, "run-commands")
d = js(r) or {}
check("run-commands runs each command and records every exit", r.returncode == 0 and d.get("ok") is True and
      sum(1 for x in d["results"] if x.get("exit") == 0) == 4 and any(x.get("skipped") for x in d["results"]), r.stdout + r.stderr)
doc = json.loads(orig)
doc["packages"][0]["commands"]["test"] = FAIL
open(cj, "w").write(json.dumps(doc))
r = sc(repo, "run-commands")
check("a failing command fails the run and says to fix the skeleton, not the command", r.returncode == 1 and (js(r) or {}).get("ok") is False and "Fix the skeleton" in r.stdout, r.stdout)
open(cj, "w").write(orig)
sc(repo, "run-commands")

# --- rules, hooks, ci, claude.md, ownership ----------------------------------------------------
print("\n# files and ownership")
for step in ("rules", "git-hooks", "ci", "claude-md"):
    r = sc(repo, "render", step)
    check(f"render {step}", r.returncode == 0, r.stderr)
check("rules are written under .claude/rules/rebuild-*", os.path.exists(os.path.join(repo, ".claude", "rules", "rebuild-code-style.md")))
check("the rules carry path globs for the package", "paths:" in open(os.path.join(repo, ".claude", "rules", "rebuild-code-style.md")).read())
ci = open(os.path.join(repo, ".github", "workflows", "rebuild-verify.yml")).read()
check("CI runs the recorded commands", "- run: " + OK in ci and "working-directory: ." in ci, ci)
check("the commit-msg check is the plugin's commit_rules.py, byte for byte (one source of the rule)",
      sha(os.path.join(repo, "scripts", "commit_msg.py")) == sha(os.path.join(ROOT, "hooks", "scripts", "commit_rules.py")))
check("the launcher is vendored too", sha(os.path.join(repo, "scripts", "py.sh")) == sha(os.path.join(ROOT, "hooks", "py.sh")))
claude_md = open(os.path.join(repo, "CLAUDE.md")).read()
check("CLAUDE.md is the thin pointer: workbench path and the five commands, no rules brief",
      "../wb1" in claude_md and "install, build, lint, typecheck, test" in claude_md and len(claude_md.splitlines()) <= 6, claude_md)

seeded = os.path.join(repo, "seeded.txt")
with open(seeded, "a") as f:
    f.write("edited by a person\n")
r = sc(repo, "render", "files")
check("a seeded file a person edited is refused with a diff, exit 2", r.returncode == 2 and "has been edited" in r.stderr and "edited by a person" not in r.stdout
      and "would write" in r.stderr, r.stderr + r.stdout)
check("…and left exactly as they left it", open(seeded).read().endswith("edited by a person\n"))
gen = os.path.join(repo, "gen.txt")
open(gen, "w").write("hand edit\n")
r = sc(repo, "render", "files")
check("a generated file is rewritten freely", open(gen).read() == "generated\n")
open(os.path.join(repo, "CLAUDE.md"), "a").write("my own line\n")
sc(repo, "render", "claude-md")
check("CLAUDE.md is user-owned: written once and never touched again", open(os.path.join(repo, "CLAUDE.md")).read().endswith("my own line\n"))
os.remove(seeded)
sc(repo, "render", "files")  # restore for the commit below
open(seeded).read()

# --- the git hooks actually block ---------------------------------------------------------------
print("\n# git hooks")
hooks = os.path.join(repo, ".git", "hooks")
check("both shims are installed and marked as ours", all("# rebuild hook shim" in open(os.path.join(hooks, h)).read() for h in ("pre-commit", "commit-msg")))
foreign = os.path.join(base, "foreignrepo")
os.makedirs(foreign)
git(foreign, "init", "-q")
open(os.path.join(foreign, ".git", "hooks", "pre-commit"), "w").write("#!/bin/sh\necho theirs\n")
r = sc(foreign, "install-hooks", "--dir", foreign)
check("a hook that is not ours is never clobbered", "foreign hook left in place" in r.stdout and "theirs" in open(os.path.join(foreign, ".git", "hooks", "pre-commit")).read(), r.stdout)
git(repo, "add", "-A")
r = git(repo, "commit", "-qm", "wip stuff")
check("the commit-msg hook blocks a non-Conventional subject", r.returncode != 0 and "Conventional Commit" in (r.stderr + r.stdout), r.stderr + r.stdout)
r = git(repo, "commit", "-qm", "feat: add the thing")
check("…and lets a Conventional one through the pre-commit gate", r.returncode == 0, r.stderr + r.stdout)
doc = json.loads(orig)
doc["packages"][0]["commands"]["lint"] = FAIL
open(cj, "w").write(json.dumps(doc))
open(os.path.join(repo, "more.txt"), "w").write("x")
git(repo, "add", "-A")
r = git(repo, "commit", "-qm", "feat: second")
check("the pre-commit gate runs lint and blocks when it fails", r.returncode != 0 and "lint failed" in (r.stderr + r.stdout), r.stderr + r.stdout)
open(cj, "w").write(orig)
git(repo, "reset", "-q")

# --- resume, finalize, drift --------------------------------------------------------------------
print("\n# resume and finalize")
st = js(sc(repo, "status")) or {}
check("status reports where setup stands", st.get("setup") == "in_progress" and st.get("next") == "finalize", json.dumps(st))
r = sc(repo, "finalize")
check("finalize moves the lock to .rebuild/ and marks setup complete", r.returncode == 0 and os.path.exists(os.path.join(repo, ".rebuild", "scaffold.lock.json"))
      and not os.path.exists(os.path.join(repo, ".git", "rebuild-scaffold.lock.json")), r.stderr)
st = js(sc(repo, "status", "--drift")) or {}
check("status --drift reports against the installed plugin and names edited files", st.get("setup") == "complete" and st.get("drift") == "current", json.dumps(st))

dead = fresh_repo("repo2")
wb2 = workbench("wb2", manifest())
bad_gen = manifest()
bad_gen["packages"][0]["options"]["go"]["generator"] = [FAIL]
wb3 = workbench("wb3", bad_gen)
sc(dead, "init", "--workbench", wb3, "--choose", "api=go", "--set", "org=acme", "--approved-by", "Eval")
r = sc(dead, "generate", "api")
st = js(sc(dead, "status")) or {}
r2 = sc(dead, "finalize")
check("finalize refuses while steps are missing", r2.returncode == 1 and "not finished" in r2.stderr, r2.stderr)
check("a generator that dies leaves the step unrecorded, so the run resumes there",
      r.returncode == 1 and "generator failed" in r.stderr and st.get("next") == "skeleton:api" and st.get("setup") == "in_progress", r.stderr + json.dumps(st))

# --- layout ---------------------------------------------------------------------------------------
print("\n# layout")
two = manifest()
two["packages"].append({"name": "web", "path": ".", "monorepoPath": "apps/web", "options": {"only": two["packages"][0]["options"]["alt"]}})
wb4 = workbench("wb4", two)
mono = fresh_repo("repo3")
r = sc(mono, "plan", "--workbench", wb4, "--choose", "api=go", "--set", "org=acme")
check("two packages at one path in a polyrepo are refused with the way out", r.returncode == 1 and "--monorepo" in r.stderr, r.stderr)
r = sc(mono, "plan", "--workbench", wb4, "--choose", "api=go", "--set", "org=acme", "--monorepo")
paths = [p["path"] for p in (js(r) or {}).get("proposal", {}).get("packages", [])]
check("--monorepo puts each package under its monorepoPath", paths == ["apps/api", "apps/web"], str(paths))

shutil.rmtree(base, ignore_errors=True)
print(f"\n{failures} failure(s)." if failures else "\nall passed")
sys.exit(1 if failures else 0)
