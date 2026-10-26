#!/usr/bin/env python3
"""upgrade.py — re-copy scripts and schemas from the installed plugin into this workbench.
Run from the workbench root.
Usage:
  python3 scripts/upgrade.py                     # dry run: what would change, and nothing else
  python3 scripts/upgrade.py --apply             # copy the safe ones; refuse locally modified
  python3 scripts/upgrade.py --apply --force scripts/gate.py,schemas/rule.schema.json
  python3 scripts/upgrade.py --diff scripts/gate.py   # full diff for one file
  python3 scripts/upgrade.py --keep scripts/parity.py # record: keep OUR version of this one
  python3 scripts/upgrade.py --plugin <path>     # override where the plugin lives
  python3 scripts/upgrade.py --auto [--plugin <path>]  # session start: apply the safe ones if
                                                       # now is a safe moment, commit, one line

Standard library only, like every other script a hand-upgraded workbench might run while parts
of its tooling are missing or stale — which is most likely exactly when someone runs this one.

WHY A WORKBENCH NEEDS UPGRADING AT ALL

rebuild_init.py vendors the schemas and tooling scripts INTO each workbench at scaffold
time, deliberately: a workbench is a self-contained, versioned copy, and a project mid-G4 is
not improved by its tooling changing underneath it. The cost is that a workbench scaffolded
before a release never receives that release's new files, so a reference doc telling you to
run `python3 scripts/preflight.py` names a script that does not exist. Until now the answer was
a `cp` line in docs/PLAYBOOK.md per release, which does not scale past about two.

THE HARD PART IS NOT COPYING, IT IS KNOWING WHAT YOU WOULD DESTROY

Some workbenches have LOCAL EDITS to their vendored scripts — a project-specific check bolted
onto validate.py, a parity report with an extra section. A blind re-copy silently deletes
that work, and it deletes it from the one repo whose whole purpose is holding decisions that
cannot be reproduced. So this script never overwrites a file it cannot prove is untouched.

Proof comes from `locks/tooling.json`, a manifest of sha256 hashes written by rebuild_init.py
at scaffold time and rewritten here after every apply. A file whose hash matches the manifest
is a pristine vendored copy and safe to replace. A file whose hash does not is LOCALLY
MODIFIED and is refused, with the diff, until a human says otherwise with --force.

A workbench scaffolded before the manifest existed has no baseline at all. That case is
treated as unknown-provenance rather than as unmodified: every differing file is refused the
same way, because "I cannot tell whether you wrote this" and "you wrote this" deserve the
same caution and only one of them is safe to guess at.

A REFUSAL MUST NOT DECAY INTO AN OVERWRITE

The first version of this script recorded a refused file's CURRENT hash into the baseline,
reasoning that a decision to keep a local edit should not be re-litigated every release. That
was exactly backwards: on the next run the file matched its baseline and differed from the
plugin, which is the definition of `stale` here — so `--apply` copied over it and the local
edit was destroyed silently, one release after being deliberately protected. Refusing loudly
and then quietly overwriting later is worse than never refusing at all.

So a refused file's baseline is left ALONE and it keeps reporting as modified until a human
acts. `--keep` is the way to act without losing the edit: it records the local version in a
separate `kept:` map, and a kept file is reported every run, never copied, and never counted
as up to date. The nag becomes one quiet line instead of a wall of text, which was the real
problem the bad design was trying to solve.

FILES DEPEND ON EACH OTHER, AND A FORCED UPGRADE CAN BREAK THE ONES IT LEAVES

Every file is classified on its own, but scripts import each other. A 0.22.0 -> 0.31.0 upgrade
forced the plugin's acsuite over a kept slice-review that called an export the new
acsuite no longer had, and slice-review crashed (`acLib.pickRun is not a function`). So the
set of scripts as it will be AFTER this run is checked for imports that no longer resolve,
and an --apply runs validate and gate status before and after, and says when either got worse.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone


# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's _read_text for the incident.
def read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        return re.sub(r"\r\n?", "\n", fh.read())


def _join(*parts):
    # Node's path.join with no arguments is "."; os.path.join raises.
    return os.path.normpath(os.path.join(*parts)) if parts else "."


def _iso_now():
    t = datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _read_bytes(p):
    with open(p, "rb") as fh:
        return fh.read()


def _hex(buf):
    return hashlib.sha256(buf).hexdigest()


def _to_lf(buf):
    return buf.decode("utf-8", errors="replace").replace("\r\n", "\n").encode("utf-8")


# A file's hash as it is on disk AND with CRLF turned to LF. With core.autocrlf=true, a vendored
# copy re-checked-out from git is CRLF while its recorded hash is of the plugin's LF bytes, so a
# pristine copy read as `modified` on every clone. Either form matches, which keeps hashes
# recorded before this change (some of them CRLF, for `kept`) valid.
def sha(p):
    return _hex(_read_bytes(p))


def shas(p):
    buf = _read_bytes(p)
    return {_hex(buf), _hex(_to_lf(buf))}


def lf_sha(p):
    return _hex(_to_lf(_read_bytes(p)))


def _is_file(p):
    return os.path.isfile(p)


def _git_out(args):
    # stderr stays inherited, as the Node twin's execFileSync left it: git's own complaint is
    # the only explanation for a "git unavailable" deferral.
    return subprocess.run(["git", *args], check=True, stdout=subprocess.PIPE, text=True,
                          encoding="utf-8").stdout


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    def has(f):
        return f in args

    def arg_after(f):
        i = args.index(f) if f in args else -1
        return (args[i + 1] if i + 1 < len(args) else None) if i != -1 else None

    # Paths the user names, in the manifest's form. `rel` is built with join(), so the manifest holds
    # `scripts\gate.py` on Windows and `--force scripts/gate.py` was refused as "not a vendored
    # file". Keys stay native rather than moving to "/" so an existing Windows manifest still matches.
    def native(p):
        return _join(*[x for x in re.split(r"[\\/]", p) if x])

    def path_list(flag):
        return [native(x.strip()) for x in (arg_after(flag) or "").split(",") if x.strip()]

    if not os.path.exists(_join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1

    # --- where the plugin lives -----------------------------------------------------------
    # --plugin wins, then the .rebuild-plugin marker rebuild_init.py writes at scaffold time,
    # then the environment variable the skill runs under. Marker before env on purpose: a
    # workbench can outlive the session that made it, and a stale env var pointing at a plugin
    # copy that was since moved would upgrade from the wrong source without saying so.
    marker_path = ".rebuild-plugin"
    from_marker = None
    if os.path.exists(marker_path):
        from_marker = next((l for l in (x.strip() for x in read_text(marker_path).split("\n"))
                            if l and not l.startswith("#")), None)

    # An installed plugin lives in a per-version cache directory (…/plugins/cache/<market>/<name>/
    # <version>/), and the marker rebuild_init.py wrote points at whichever version scaffolded the
    # workbench. Read literally, that marker pins upgrades to the old version forever: the plugin
    # updates, the marker does not, and every run reports "up to date" against a copy nobody runs.
    # So a marker or env path inside the cache follows to the newest installed version beside it.
    # An explicit --plugin is taken as given.
    def newest_cached(p):
        if not p:
            return p
        m = re.match(r"(.*[/\\]plugins[/\\]cache[/\\].+)[/\\]([0-9]+\.[0-9]+\.[0-9]+)[/\\]?\Z", os.path.abspath(p))
        if not m:
            return p

        def ver(v):
            return tuple(int(x) for x in v.split("."))

        best = m.group(2)
        try:
            for v in os.listdir(m.group(1)):
                if (re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", v)
                        and os.path.exists(_join(m.group(1), v, "skills", "rebuild-pipeline"))
                        and ver(v) > ver(best)):
                    best = v
        except OSError:
            return p
        return _join(m.group(1), best)

    plugin_root = arg_after("--plugin") or newest_cached(from_marker or os.environ.get("CLAUDE_PLUGIN_ROOT")) or None
    if not plugin_root:
        print(
            "Cannot find the plugin. This workbench has no `.rebuild-plugin` marker (it was scaffolded\n"
            "before 0.17.0) and CLAUDE_PLUGIN_ROOT is not set. Pass it explicitly, and write the marker\n"
            "so this is a one-time problem:\n"
            "  python3 scripts/upgrade.py --plugin /path/to/product-rebuild\n"
            "  echo /path/to/product-rebuild > .rebuild-plugin", file=sys.stderr)
        return 1
    SRC = _join(plugin_root, "skills", "rebuild-pipeline")
    if not os.path.exists(_join(SRC, "scripts")) or not os.path.exists(_join(SRC, "schemas")):
        print(f"Not a product-rebuild plugin root: {plugin_root}\n"
              f"  Expected {_join(SRC, 'scripts')} and {_join(SRC, 'schemas')}.", file=sys.stderr)
        return 1

    plugin_version = "unknown"
    try:
        with open(_join(plugin_root, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            plugin_version = json.load(fh).get("version") or "unknown"
    except Exception:
        plugin_version = "unknown"

    # --- the major fence -------------------------------------------------------------------
    # 1.x never touches a workbench a 0.x release made. This runs at every session start through
    # --auto, so a user who installed 1.x beside a rebuild still in flight would otherwise have
    # 1.x's scripts copied over their 0.x ones: different scripts, different guards, no migration.
    # `rebuild_major:` in locks/pipeline.yaml is what rebuild_init.py writes; its absence means 0.x
    # by definition. Nothing is copied, committed or rewritten, and --auto prints its one line and
    # exits 0, because a session start must never fail on a workbench that is simply someone else's.
    marker_major = None
    try:
        with open(_join("locks", "pipeline.yaml"), encoding="utf-8") as fh:
            mm = re.search(r"^rebuild_major:\s*([0-9]+)", fh.read().replace("\r\n", "\n"), re.M)
        marker_major = int(mm.group(1)) if mm else None
    except OSError:
        pass
    if marker_major is None or marker_major < 1:
        fence = (f"This workbench was made by a 0.x release of the pipeline (locks/pipeline.yaml has no `rebuild_major`), "
                 f"and plugin {plugin_version} (1.x) will not touch it: the scripts, the guards and the way repos are "
                 f"created all differ, and there is no migration. Finish it on the 0.x line.")
        if has("--auto"):
            print(f"TOOLING  skipped: {fence}")
            return 0
        print(fence, file=sys.stderr)
        return 1

    # --- what is vendored ------------------------------------------------------------------
    # Everything the plugin ships under scripts/ and schemas/, minus rebuild_init.py — that one
    # scaffolds workbenches and is never run from inside one — plus the vendored PyYAML tree the
    # scripts import through yamlio.py. Enumerating the source rather than carrying a hard-coded
    # list is what keeps a future script from being forgotten here, which is the failure this
    # whole file exists to stop repeating. Bytecode is skipped: it is per-interpreter local state.
    vendored = []
    scripts_src = _join(SRC, "scripts")
    for f in sorted(os.listdir(scripts_src)):
        if f.endswith(".py") and f != "rebuild_init.py" and _is_file(_join(scripts_src, f)):
            vendored.append({"rel": _join("scripts", f), "src": _join(scripts_src, f)})
    tree_src = _join(scripts_src, "_vendor", "pyyaml")
    for dirpath, dirs, names in os.walk(tree_src):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for n in sorted(names):
            if n.endswith(".pyc"):
                continue
            sub = os.path.relpath(os.path.join(dirpath, n), tree_src)
            vendored.append({"rel": _join("scripts", "_vendor", "pyyaml", sub),
                             "src": os.path.join(dirpath, n)})
    schemas_src = _join(SRC, "schemas")
    for f in sorted(os.listdir(schemas_src)):
        if f.endswith(".json"):
            vendored.append({"rel": _join("schemas", f), "src": _join(schemas_src, f)})

    MANIFEST = _join("locks", "tooling.json")
    MANIFEST_COMMENT = (
        "Provenance of the vendored scripts/ and schemas/. `files` is the hash each file had when it "
        "was last vendored, which is how upgrade.py tells a stale copy from one edited here. `kept` "
        "records files whose local version a human chose to hold: reported every run, never copied "
        "over. Written by rebuild_init.py and upgrade.py. Do not hand-edit.")
    try:
        with open(MANIFEST, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception:
        manifest = None
    mf = manifest if isinstance(manifest, dict) else {}
    baseline = mf.get("files") or {}
    kept = mf.get("kept") or {}

    # --- classify --------------------------------------------------------------------------
    rows = []
    for v in vendored:
        rel, src = v["rel"], v["src"]
        src_hash = sha(src)
        row = {"rel": rel, "src": src, "srcHash": src_hash}
        if not os.path.exists(rel):
            row["state"] = "new"
            rows.append(row)
            continue
        mine = shas(rel)
        if src_hash in mine:
            row["state"] = "current"
            rows.append(row)
            continue
        # `kept` is checked FIRST and against the live hash: a file the human chose to keep, still
        # exactly as they left it, is its own state. Edited again since the decision, it drops back
        # to `modified` — the decision covered that version of the file, not the path forever.
        if kept.get(rel) in mine:
            row["state"] = "kept"
            rows.append(row)
            continue
        recorded = baseline.get(rel)
        if not recorded:
            row["state"] = "unknown"
        elif recorded in mine:
            row["state"] = "stale"
        else:
            row["state"] = "modified"
        rows.append(row)

    # --- pairs: a script and the schema for the file it writes move together ----------------
    # scripts/autopilot.py writes plan/autopilot.yaml, which validate.py checks against
    # schemas/autopilot.schema.json. Copy the new script and refuse its old schema (or the reverse)
    # and the workbench fails validation on the next write — found in a real dry run, where the
    # script was `stale` and the schema `unknown`. So when one half of a pair is refused and not
    # forced, the safe half is HELD rather than copied, until the pair can move as one.
    forced_early = set(path_list("--force"))

    def is_safe(r):
        return r["state"] in ("new", "stale")

    def is_blocked(r):
        return r["state"] in ("modified", "unknown", "kept") and r["rel"] not in forced_early

    for r in rows:
        m = re.match(r"scripts[/\\]([^/\\]+)\.py\Z", r["rel"])
        if not m:
            continue
        # Scripts are snake_case, schema names keep the hyphen (`slice-review` -> slice_review).
        mate = next((x for x in rows if x["rel"] in (
            _join("schemas", f"{m.group(1)}.schema.json"),
            _join("schemas", f"{m.group(1).replace('_', '-')}.schema.json"))), None)
        if not mate:
            continue
        for a, b in ((r, mate), (mate, r)):
            if is_safe(a) and is_blocked(b):
                a["state"] = "held"
                a["mate"] = b["rel"]

    def of(s):
        return [r for r in rows if r["state"] == s]

    def diff_of(rel, src):
        try:
            p = subprocess.run(["diff", "-u", rel, src], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding="utf-8", errors="replace")
        except OSError:
            return ""
        if p.returncode == 0:
            return ""
        return "\n".join(p.stdout.split("\n")[2:])

    def diff_stat(rel, src):
        d = diff_of(rel, src)
        if not d:
            return "no textual difference"
        plus = len(re.findall(r"^\+", d, re.M))
        minus = len(re.findall(r"^-", d, re.M))
        return f"+{plus} -{minus} lines"

    # --- --diff <file>: the full thing, for one file ---------------------------------------
    if has("--diff"):
        want = native(arg_after("--diff") or "")
        row = next((r for r in rows if r["rel"] == want or r["rel"].endswith(f"/{want}")
                    or r["rel"].endswith(f"\\{want}")), None)
        if not row:
            print(f"Not a vendored file: {want}", file=sys.stderr)
            return 1
        if row["state"] == "new":
            print(f"{row['rel']} does not exist here yet — nothing to diff.")
            return 0
        print(f"--- {row['rel']} (this workbench)\n+++ {row['src']} (plugin {plugin_version})\n")
        print(diff_of(row["rel"], row["src"]) or "(identical)")
        return 0

    # --- report ----------------------------------------------------------------------------
    # --auto prints none of this: it runs at every session start, and its output lands in the
    # orchestrator's context, where a page of file lists is paid for on every later turn.
    auto = has("--auto")

    def log(*a):
        if not auto:
            print(*a)

    if not auto:
        marker_note = "  (from .rebuild-plugin)" if from_marker and not arg_after("--plugin") else ""
        print(f"Workbench tooling vs plugin {plugin_version}")
        print(f"  plugin: {os.path.abspath(plugin_root)}{marker_note}")
        if manifest:
            baseline_line = f"{MANIFEST} (written for plugin {mf.get('plugin_version') or '?'})"
        else:
            baseline_line = "none — this workbench predates locks/tooling.json, so local edits cannot be told from staleness"
        print(f"  baseline: {baseline_line}\n")

        def show(state, label, note=None):
            lst = of(state)
            if not lst:
                return
            print(f"{label} ({len(lst)})")
            for r in lst:
                stat = "" if state == "new" else f"  [{diff_stat(r['rel'], r['src'])}]"
                print(f"  {r['rel']}{stat}")
            if note:
                print(f"  {note}")
            print("")

        show("new", "NEW — not in this workbench yet")
        show("stale", "STALE — vendored copy, unmodified, plugin has a newer one")
        show("modified", "LOCALLY MODIFIED — refused",
             "These differ from BOTH the plugin and the hash recorded when they were last vendored,\n"
             "  which means someone edited them here. Read the diff before deciding:\n"
             "    python3 scripts/upgrade.py --diff <path>\n"
             "  Then either port your change onto the plugin's version, or force this one file:\n"
             "    python3 scripts/upgrade.py --apply --force <path>")
        show("kept", "KEPT — your version, by recorded decision",
             "Never copied over, and never counted as up to date: the plugin's version has moved on and\n"
             "  yours has not. Take the plugin's with --apply --force <path>, or edit yours and re-run\n"
             "  --keep to re-record it.")
        show("unknown", "UNKNOWN PROVENANCE — refused",
             "Different from the plugin, with no recorded hash to compare against (this workbench was\n"
             "  scaffolded before locks/tooling.json). It may be an old vendored copy or your own edit —\n"
             "  this script cannot tell, and guessing wrong deletes work. Same remedy as above.")
        if of("held"):
            print(f"HELD — safe to copy, but its pair is refused ({len(of('held'))})")
            for r in of("held"):
                print(f"  {r['rel']}  (waits for {r['mate']})")
            print("  A script and the schema for the file it writes move together. Settle the refused\n"
                  "  half (--force, or port your edit), and both copy on the next --apply.\n")
        if of("current"):
            print(f"UP TO DATE ({len(of('current'))})\n")

    forced = set(path_list("--force"))
    safe = [*of("new"), *of("stale")]
    refused = [*of("modified"), *of("unknown"), *of("kept"), *of("held")]
    forced_rows = [r for r in refused if r["rel"] in forced]
    unknown_force = [f for f in forced if not any(r["rel"] == f for r in rows)]
    if unknown_force:
        print(f"--force names path(s) that are not vendored files: {', '.join(unknown_force)}", file=sys.stderr)
        return 1

    # --- imports that will not resolve after this run ---------------------------------------
    # The scripts as they will be once this run copies what it copies, local ones included, and every
    # name one of them takes from a sibling that the sibling will no longer export. Regex-read, like
    # everything else here. The import shapes the scripts use among themselves are
    # `import x`, `from x import a, b as c` (parenthesised and multi-line too), and the optional
    # `try: import x as lib / except ImportError: lib = None` followed by `lib.a`. A name a script
    # feature-detects (`lib.a if lib else ...`) is still listed — in a mixed set that is worth a
    # look, and a pristine set has none. Names reaching a sibling only through getattr() or
    # importlib are invisible here, which is why scripts import siblings by plain statement.
    will_copy = {r["rel"] for r in [*safe, *forced_rows]}
    after = {}
    if os.path.exists("scripts"):
        for f in os.listdir("scripts"):
            if f.endswith(".py") and _is_file(os.path.join("scripts", f)):
                after[f] = {"text": read_text(os.path.join("scripts", f)), "from": "this workbench"}
    for r in rows:
        m = re.match(r"scripts[/\\]([^/\\]+\.py)\Z", r["rel"])
        if m and r["rel"] in will_copy:
            after[m.group(1)] = {"text": read_text(r["src"]), "from": f"plugin {plugin_version}"}

    ident = r"[A-Za-z_][A-Za-z0-9_]*"

    def exports_of(t):
        out = set(re.findall(rf"^(?:async[ \t]+)?def[ \t]+({ident})", t, re.M))
        out |= set(re.findall(rf"^class[ \t]+({ident})", t, re.M))
        for m in re.finditer(rf"^({ident}(?:[ \t]*,[ \t]*{ident})*)[ \t]*(?::[^=\n]+)?=(?!=)", t, re.M):
            out |= {x.strip() for x in m.group(1).split(",")}
        # A top-level import binds a name another script could reach as `lib.name`.
        for m in re.finditer(r"^import[ \t]+([^\n#]+)", t, re.M):
            for part in m.group(1).split(","):
                bits = part.strip().split()
                if bits:
                    out.add(bits[-1] if len(bits) > 1 else bits[0].split(".")[0])
        for m in re.finditer(r"^from[ \t]+\S+[ \t]+import[ \t]+([^\n#(]+)", t, re.M):
            for part in m.group(1).split(","):
                bits = part.strip().split()
                if bits and bits[0] != "*":
                    out.add(bits[-1])
        return out

    def names_from(t, mod):
        names = set()
        mod_re = re.escape(mod)
        for m in re.finditer(rf"^[ \t]*from[ \t]+{mod_re}[ \t]+import[ \t]+(\([^)]*\)|[^\n]*)", t, re.M):
            body = m.group(1).strip()
            if body.startswith("("):
                body = body[1:-1]
            body = re.sub(r"#[^\n]*", "", body).replace("\\", " ")
            for part in body.split(","):
                n = part.strip().split()
                if n and n[0] != "*":
                    names.add(n[0])
        for m in re.finditer(rf"^[ \t]*(?:try:[ \t]*)?import[ \t]+{mod_re}(?:[ \t]+as[ \t]+({ident}))?[ \t]*(?:#[^\n]*)?$", t, re.M):
            var = m.group(1) or mod
            # The lookbehind skips the variable's name inside a path or a message ("scripts/erd.py").
            for u in re.finditer(rf"(?<![\w./`'\"-]){re.escape(var)}\.({ident})", t):
                if u.group(1) != "py":
                    names.add(u.group(1))
        return names

    broken_imports = []
    for importer, a in after.items():
        for mod_file, b in after.items():
            if mod_file == importer:
                continue
            exported = exports_of(b["text"])
            for name in sorted(names_from(a["text"], mod_file[:-3])):
                if name not in exported:
                    broken_imports.append({"importer": importer, "mod": mod_file, "name": name,
                                           "a": a["from"], "b": b["from"]})
    # Only the ones this run causes block --auto; one already broken before it is not its to fix.
    caused_here = [x for x in broken_imports if x["a"] != "this workbench" or x["b"] != "this workbench"]
    if broken_imports and not auto:
        print(f"BROKEN IMPORTS after this run ({len(broken_imports)})")
        for x in broken_imports:
            print(f"  {x['importer']} ({x['a']}) uses `{x['name']}` from {x['mod']} ({x['b']}), which does not export it")
        print("  Copying one half of a pair of scripts that call each other breaks the other half at\n"
              "  run time, not here. Settle them as a set: port your edit onto the plugin's version, or force\n"
              "  both files.\n")

    def write_manifest(payload):
        os.makedirs("locks", exist_ok=True)
        with open(MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    # --- --keep: record a deliberate decision to hold our own version ----------------------
    if has("--keep"):
        want = path_list("--keep")
        bad = [w for w in want if not any(r["rel"] == w for r in rows)]
        if not want or bad:
            print(f"--keep names path(s) that are not vendored files: {', '.join(bad)}" if bad
                  else "--keep needs at least one path, e.g. --keep scripts/parity.py", file=sys.stderr)
            return 1
        next_kept = dict(kept)
        # The LF hash, so the decision survives the file being re-checked-out as CRLF.
        for w in want:
            next_kept[w] = lf_sha(w)
        write_manifest({**mf, "comment": MANIFEST_COMMENT,
                        "plugin_version": mf.get("plugin_version") or plugin_version,
                        "updated": _iso_now(), "files": baseline, "kept": next_kept})
        print(f"Recorded as KEPT: {', '.join(want)}.")
        print("These are now reported every run and never copied over. Editing one again drops it "
              "back to `modified` — the decision covers the version you have, not the path forever.")
        return 0

    def refused_line():
        if not refused:
            return ""
        names = ", ".join(re.split(r"[\\/]", r["rel"])[-1] for r in refused)
        return f" {len(refused)} refused ({names}) — run `python3 scripts/upgrade.py` to see why."

    # --- --auto: the session-start path -----------------------------------------------------
    # Applies only the files this script can prove are pristine, and only at a moment when tooling
    # changing underneath the work cannot hurt: no slice in progress, no engaged autopilot run, a
    # clean tree (so the upgrade lands as its own commit and `gate.py lock` is not left facing a
    # dirty one). Anything else defers to a later session start. It never forces and never keeps;
    # refused files are named in one line for a human to settle.
    if auto:
        if forced or has("--keep"):
            print("--auto takes neither --force nor --keep.", file=sys.stderr)
            return 1
        if not safe:
            print(f"TOOLING  up to date with plugin {plugin_version}.{refused_line()}")
            return 0
        why = []
        try:
            if _git_out(["status", "--porcelain"]).strip():
                why.append("uncommitted changes")
        except Exception:
            why.append("git unavailable")
        prog = read_text(_join("plan", "progress.yaml")) if os.path.exists(_join("plan", "progress.yaml")) else ""
        in_prog = re.search(r"^\s+(S[0-9]+):\s*in-progress\s*$", prog, re.M)
        if in_prog:
            why.append(f"{in_prog.group(1)} in progress")
        ap = read_text(_join("plan", "autopilot.yaml")) if os.path.exists(_join("plan", "autopilot.yaml")) else ""
        if re.search(r"^status: engaged$", ap, re.M):
            why.append("autopilot engaged")
        if caused_here:
            why.append(f"it would break {len(caused_here)} import(s) between scripts")
        if why:
            print(f"TOOLING  {len(safe)} update(s) from plugin {plugin_version} deferred — {', '.join(why)}. "
                  f"Applies at a session start with none of those true.{refused_line()}")
            return 0

    if not has("--apply") and not auto:
        print(f"Dry run. {len(safe)} file(s) would be copied. Re-run with --apply." if safe or forced_rows
              else "Dry run. Nothing to copy.")
        if refused:
            print(f"{len(refused)} file(s) would be REFUSED (see above).")
        return 0

    # --- apply ------------------------------------------------------------------------------
    # What validate and gate status say, taken before and after copying. A script that cannot read
    # this workbench's data any more (a schema that rejects a status the workbench uses, a parser
    # that misreads its files) shows up here as a worse answer from the same command, which is the
    # only comparison that does not need to know what changed.
    def health():
        def run(*a):
            try:
                p = subprocess.run([sys.executable, *a], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace")
            except OSError:
                return {"ok": False, "out": ""}
            if p.returncode == 0:
                return {"ok": True, "out": p.stdout}
            return {"ok": False, "out": f"{p.stdout}{p.stderr}"}

        v = run(_join("scripts", "validate.py"))["ok"] if os.path.exists(_join("scripts", "validate.py")) else None
        g = run(_join("scripts", "gate.py"), "status")
        if g["ok"]:
            pm = re.search(r"^(?:Current phase: .*|All gates locked.*)$", g["out"], re.M)
            phase = pm.group(0) if pm else "(no phase line)"
        else:
            first = g["out"].strip().split("\n")[0]
            phase = f"gate.py status failed: {first or 'no output'}"
        return {"validate": v, "phase": phase}

    before = health()
    existed_before = {r["rel"] for r in [*safe, *forced_rows] if os.path.exists(r["rel"])}
    copied = []
    for r in [*safe, *forced_rows]:
        os.makedirs(os.path.dirname(r["rel"]) or ".", exist_ok=True)
        shutil.copy(r["src"], r["rel"])
        copied.append(r)
        note = "  (FORCED — your version is gone; git has it if it was committed)" if r["rel"] in forced else ""
        log(f"copied  {r['rel']}{note}")

    # Rewrite the baseline for the files this run actually vendored, and for those ONLY.
    #
    # A refused file keeps whatever baseline it had. Recording its current hash instead would make
    # today's local edit tomorrow's baseline, so the next run would classify it `stale` — clean
    # vendored copy, behind the plugin — and `--apply` would copy straight over the edit that was
    # deliberately protected one release earlier. A refusal that decays into a silent overwrite is
    # worse than no refusal at all, which is why `--keep` exists as the explicit way to settle one.
    files = dict(baseline)
    for r in copied:
        files[r["rel"]] = r["srcHash"]
    for v in vendored:
        if not os.path.exists(v["rel"]):
            files.pop(v["rel"], None)
    write_manifest({"comment": MANIFEST_COMMENT, "plugin_version": plugin_version,
                    "updated": _iso_now(), "files": files, "kept": kept})

    if auto:
        # One commit, so a regression bisects to it and `git revert` undoes the whole upgrade.
        committed = False
        try:
            subprocess.run(["git", "add", "--", *[r["rel"] for r in copied], MANIFEST], check=True, capture_output=True)
            subprocess.run(["git", "commit", "-qm", f"tooling: upgrade vendored scripts/schemas to plugin {plugin_version}"],
                           check=True, capture_output=True)
            committed = True
        except Exception:
            pass  # reported below
        now = health()
        if now["validate"] is None:
            valid = "not run (no scripts/validate.py)"
        elif now["validate"]:
            valid = "passes"
        elif before["validate"]:
            valid = "FAILS, and passed before this upgrade — `git revert HEAD` undoes it; run `python3 scripts/validate.py` to see why"
        else:
            valid = "FAILS (failed before this upgrade too) — run `python3 scripts/validate.py` and read it before any other work"
        phase_note = (f' gate status changed: "{before["phase"]}" → "{now["phase"]}" — check which is right before any other work.'
                      if now["phase"] != before["phase"] else "")
        print(f"TOOLING  upgraded {len(copied)} file(s) to plugin {plugin_version}" +
              (", committed" if committed else " — NOT committed, commit it before anything else") +
              f"; validate {valid}.{phase_note}{refused_line()}")
        return 0

    print(f"\n{len(copied)} file(s) copied from plugin {plugin_version}. Baseline rewritten: {MANIFEST}.")
    still_refused = [r for r in refused if r["rel"] not in forced and r["state"] != "kept"]
    if still_refused:
        print(f"{len(still_refused)} file(s) left alone: {', '.join(r['rel'] for r in still_refused)}.")
        print("Their baseline is unchanged, so they will be refused again next run — that is the "
              "point. To settle one: port your change onto the plugin's version and re-run, take the "
              "plugin's with `--apply --force <path>`, or hold yours on the record with `--keep <path>`.")

    now = health()
    worse = []
    if before["validate"] and now["validate"] is False:
        worse.append("validate passed before this run and FAILS now (python3 scripts/validate.py)")
    if now["phase"] != before["phase"]:
        worse.append(f'gate status said "{before["phase"]}" and now says "{now["phase"]}"')
    if worse:
        print("\nWARNING — this upgrade changed what the workbench reports:\n" + "\n".join(f"  - {w}" for w in worse))
        print("  A changed phase can be a fix (a parser that now reads the file correctly) or a break;\n"
              "  read both before deciding. To undo the whole run, if these files were committed before it:")
        restore = [r["rel"] for r in copied if r["rel"] in existed_before]
        added = [r["rel"] for r in copied if r["rel"] not in existed_before]
        if restore:
            print(f"    git checkout -- {' '.join([*restore, MANIFEST])}")
        else:
            print(f"    git checkout -- {MANIFEST}")
        if added:
            print(f"    and delete the file(s) this run added: {', '.join(added)}")
    elif now["validate"] is None:
        print("validate not run (no scripts/validate.py) — run `python3 scripts/validate.py` before anything else.")
    else:
        print(f"validate {'passes' if now['validate'] else 'fails, as it did before this run'}; gate status unchanged.")
    print("Commit this in one go: a half-upgraded workbench is the state nothing else in the pipeline expects.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
