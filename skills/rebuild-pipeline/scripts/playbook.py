#!/usr/bin/env python3
"""playbook.py — the architecture playbook a rebuild's code repos are created from.

Usage (from the workbench root):
  python3 scripts/playbook.py vendor [--plugin <plugin root>]

`vendor` copies the playbook sources.yaml selects (or the org default) to adr/playbook.md and its scaffold
manifest to adr/playbook.scaffold.json, where gate-3 locks them with rspec's ADRs and scaffold-repo reads them.
The rest is a library shared by validate.py, gate.py and scaffold-repo's scaffold.py: what Gate 3 accepts is
exactly what G5 can scaffold. Since 3.0.0 the ADRs are rspec's (docs/decisions/) and the playbook reaches
rspec:tech as a stack preference; adr/ holds only the vendored playbook and its manifest, so the stack a code
repo is created from cannot change under a project when the plugin upgrades.

Standard library only by necessity: gate.py runs with nothing but its sibling scripts present.
So the formats this file reads are parsed by line, not by yamlio, and
both line-parsed formats are ones this pipeline defines rather than inherits:

  1. `architecture:` in sources.yaml — two scalar keys, one nesting level.
  2. The frontmatter block of a playbook in references/playbooks/ — scalars, one list,
     and two single-level maps (`concerns:`, `decide-before:`).
  3. The playbook's scaffold manifest, which is JSON precisely because (2) is not YAML: what
     a scaffold needs — packages, options per stack, generator commands, five commands each —
     is a list of maps of lists, and fitting it into the line parser would have meant
     growing the parser into the YAML library this file exists to avoid.

Deliberately NOT a YAML parser, and deliberately not tolerant of clever YAML: anchors,
folded scalars and flow mappings are not supported anywhere in these two blocks. A
playbook that needs them is a playbook whose frontmatter has outgrown its job.

Result shapes are dicts with snake_case keys (the .mjs twin used camelCase objects):
`target_shape`, `selected_by`, `missing_vendored`, `not_applicable_when`, `decide_before`,
`org_default`.
"""
from __future__ import annotations

import json
import os
import re
import sys

# Every file this module reads is hand-edited, and one of them will be edited on Windows.
# Splitting a CRLF file on "\n" leaves a `\r` on every line, and a `.` does not match it in the
# Node twin (it is a line terminator there), so a `(.*)$` pattern failed on every *value* line
# while the block *header* still matched — the mechanism then reported "no playbook selected"
# rather than "unparsable", and every check silently switched off, from a CRLF `sources.yaml`
# whose LF twin refused correctly. Normalize once at every read instead of trusting each
# pattern to be CRLF-safe.
def _strip_cr(s):
    return re.sub(r"\r\n?", "\n", s)


def _read_text(p):
    # errors="replace": a stray byte must not abort a gate check (the Node twin decoded the
    # same way), and the markers these scripts look for are all ASCII.
    with open(p, encoding="utf-8", errors="replace", newline="") as fh:
        return _strip_cr(fh.read())


def _join(*parts):
    # normpath so `join(".", "adr")` reads `adr`, not `./adr`: paths appear verbatim in
    # messages, and the Node twin's path.join normalised the same way.
    return os.path.normpath(os.path.join(*parts))


def _js_str(v):
    """Interpolate a JSON value the way the Node twin's template strings did."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    if isinstance(v, list):
        return ",".join("" if x is None else _js_str(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


# Where `vendor` copies the selected playbook. Inside gate-3's `protects:` (`adr/`) on purpose.
VENDORED_PLAYBOOK = "adr/playbook.md"

# Where `vendor` copies the playbook's scaffold manifest, beside it and for the same reason: a
# lock that hashes the ADRs but not the stack they chose would let the scaffold drift from
# what Gate 3 approved. With `architecture.playbook: none` there is no registry manifest, so
# the project writes its own at SCAFFOLD_LOCAL — same format, same checks, same lock.
VENDORED_SCAFFOLD = "adr/playbook.scaffold.json"
SCAFFOLD_LOCAL = "adr/scaffold.json"

# Registry path inside the plugin; `vendor` copies from it, nothing else in the workbench reads it.
REGISTRY_DIR = "skills/rebuild-pipeline/references/playbooks"

# The playbook a project gets when `sources.yaml` names none. Not a convenience default: treating
# the blank scaffolded value as "no playbook, run no checks" once left the *most common*
# configuration unenforced while the docs claimed otherwise.
DEFAULT_PLAYBOOK = "web-modular-monolith"


def is_pre_playbook_workbench(root="."):
    """True for workbenches scaffolded before the playbook registry existed. They get warnings
    where a new workbench gets errors. The signal is `locks/pipeline.yaml`'s schema_version, because `protects:`
    already covers `adr/` in every workbench ever scaffolded and so cannot tell old from new."""
    p = _join(root, "locks", "pipeline.yaml")
    if not os.path.exists(p):
        return True
    m = re.search(r'^schema_version:\s*"?([0-9.]+)"?', _read_text(p), re.M)
    if not m:
        return True
    parts = [int(x) if x else 0 for x in m.group(1).split(".")]
    major = parts[0]
    # A one-part version has no minor: the Node twin compared `undefined < 3`, which is false.
    return major == 0 and len(parts) > 1 and parts[1] < 3


def _unquote(s):
    return re.sub(r"""\A["'](.*)["']\Z""", r"\1", s.strip(), flags=re.S).strip()


def read_architecture_config(root="."):
    """Read `architecture:` out of sources.yaml. An absent block or empty value reads as None
    here; `check_playbook` is what resolves None to `DEFAULT_PLAYBOOK`."""
    p = _join(root, "sources.yaml")
    out = {"playbook": None, "target_shape": None}
    if not os.path.exists(p):
        return out
    lines = _read_text(p).split("\n")
    start = next((i for i, l in enumerate(lines) if re.match(r"architecture:\s*\Z", l)), -1)
    if start == -1:
        return out
    for line in lines[start + 1:]:
        if re.match(r"\S", line):
            break                               # dedent ends the block
        m = re.match(r"\s+([A-Za-z0-9_-]+):\s*(.*)\Z", line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        val = _unquote(re.sub(r"\s+#.*\Z", "", raw, count=1))
        if not val:
            continue
        if key == "playbook":
            out["playbook"] = val
        if key in ("target_shape", "target-shape"):
            out["target_shape"] = val
    return out


def parse_playbook_meta(raw_text):
    """Parse a playbook's frontmatter. Returns None when the file has no `---` block at all —
    which is the one failure worth distinguishing, because it means the file predates the
    registry (or is not a playbook) rather than being malformed."""
    text = _strip_cr(raw_text)
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return None
    meta = {
        "playbook": None, "stack": None, "target_shape": None, "scaffold": None,
        "not_applicable_when": [], "concerns": {}, "decide_before": {},
    }
    block = None  # "not-applicable-when" | "concerns" | "decide-before"
    for raw in m.group(1).split("\n"):
        if not raw.strip() or re.match(r"\s*#", raw):
            continue
        top = re.match(r"([A-Za-z0-9_-]+):\s*(.*)\Z", raw)
        if top:
            key, rest = top.group(1), top.group(2)
            val = _unquote(rest)
            block = None
            if key == "playbook":
                meta["playbook"] = val
            elif key == "stack":
                meta["stack"] = val
            elif key in ("target-shape", "target_shape"):
                meta["target_shape"] = val
            elif key == "scaffold":
                meta["scaffold"] = val
            elif key == "not-applicable-when":
                block = "not-applicable-when"
            elif key == "concerns":
                block = "concerns"
            elif key == "decide-before":
                block = "decide-before"
            continue
        item = re.match(r"\s+-\s+(.*)\Z", raw)
        if item and block == "not-applicable-when":
            meta["not_applicable_when"].append(_unquote(item.group(1)))
            continue
        pair = re.match(r"\s+([A-Za-z0-9_-]+):\s*(.*)\Z", raw)
        if pair and block in ("concerns", "decide-before"):
            value = _unquote(pair.group(2))
            if block == "concerns":
                meta["concerns"][pair.group(1)] = value
            else:
                meta["decide_before"][pair.group(1)] = [s.strip() for s in value.split(",") if s.strip()]
    return meta


# The scaffold manifest contract. scaffold-repo reads the same file through this module, so what
# Gate 3 accepts is exactly what G5 can run. See references/playbooks/README.md for the format.
COMMAND_KEYS = ["install", "build", "lint", "typecheck", "test"]
CI_SETUPS = ["go", "node", "flutter", "none"]
_FILE_CLASSES = ["generated", "seeded", "user"]
_SLUG = re.compile(r"[a-z][a-z0-9-]*\Z")
# Ask keys also allow underscores (`bundle_org`): they are placeholder names, not file or package names.
_ASK_KEY = re.compile(r"[a-z][a-z0-9_-]*\Z")
# Placeholders every package supplies itself; `ask:` keys may not shadow them.
BUILTIN_VARS = ["name", "path", "repo", "subpath"]


def _placeholders(s):
    return [m.group(1) for m in re.finditer(r"\{\{\s*([A-Za-z0-9_-]+)\s*\}\}", _js_str(s))]


def _is_obj(v):
    return isinstance(v, dict)


def _slug(v):
    return isinstance(v, str) and _SLUG.match(v) is not None


def _strs(a):
    return isinstance(a, list) and all(isinstance(x, str) for x in a)


def _len(v):
    return len(v) if isinstance(v, (list, str)) else 0


def _compact(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def scaffold_problems(m):
    """Problems with a parsed manifest, as strings; empty means it will scaffold."""
    out = []
    if not _is_obj(m):
        return ["the scaffold manifest is not a JSON object"]
    known = ["ask", "ci", "packages"]
    for k in m:
        if k not in known:
            out.append(f'unknown key "{k}" (known: {", ".join(known)}) — a typo here is silently ignored otherwise')
    ask_keys = set()
    ask = m.get("ask")
    for a in (ask if isinstance(ask, list) else []):
        if not _is_obj(a) or not (isinstance(a.get("key"), str) and _ASK_KEY.match(a["key"])) or not isinstance(a.get("prompt"), str):
            out.append(f"ask entry needs a `key` (lowercase, digits, - or _) and a `prompt`: {_compact(a)}")
            continue
        if a["key"] in BUILTIN_VARS:
            out.append(f'ask key "{a["key"]}" shadows a built-in placeholder ({", ".join(BUILTIN_VARS)})')
        if a["key"] in ask_keys:
            out.append(f'ask key "{a["key"]}" is declared twice')
        ask_keys.add(a["key"])
    if "ask" in m and not isinstance(ask, list):
        out.append("ask must be an array")
    variables = ask_keys | set(BUILTIN_VARS)

    def check_vars(where, s):
        for v in _placeholders(s):
            if v not in variables:
                out.append(f"{where} uses {{{{{v}}}}}, which is neither an ask key nor one of {', '.join(BUILTIN_VARS)}")

    if "ci" in m:
        ci = m["ci"]
        ok = _is_obj(ci) and (
            "os" not in ci
            or (isinstance(ci["os"], list) and len(ci["os"]) > 0 and all(isinstance(o, str) for o in ci["os"])))
        if not ok:
            out.append("ci.os must be a non-empty array of runner names")
    packages = m.get("packages")
    if not isinstance(packages, list) or not packages:
        out.append("packages must be a non-empty array")
        return out
    names = set()
    for p in packages:
        pname = p.get("name") if _is_obj(p) else None
        pw = f"package {_js_str(pname) if pname is not None else '?'}"
        if not _is_obj(p) or not _slug(pname if pname is not None else ""):
            out.append(f"{pw}: name must be a slug")
            continue
        if p["name"] in names:
            out.append(f"{pw}: declared twice")
        names.add(p["name"])
        options = p.get("options")
        if not _is_obj(options) or not options:
            out.append(f"{pw}: options must name at least one stack")
            continue
        for opt, o in options.items():
            w = f'{pw} option "{opt}"'
            if not _slug(opt):
                out.append(f"{w}: option names are slugs")
            if not _is_obj(o):
                out.append(f"{w}: not an object")
                continue
            for k in o:
                if k not in ("generator", "after", "files", "commands", "ci", "toolchain"):
                    out.append(f'{w}: unknown key "{k}"')
            if not _strs(o.get("generator")):
                out.append(f"{w}: generator must be an array of shell commands (it may be empty only when files supply the skeleton)")
            else:
                for i, c in enumerate(o["generator"]):
                    check_vars(f"{w} generator[{i}]", c)
            if "after" in o:
                if not _strs(o["after"]):
                    out.append(f"{w}: after must be an array of shell commands")
                else:
                    for i, c in enumerate(o["after"]):
                        check_vars(f"{w} after[{i}]", c)
            cmds = o.get("commands")
            if not _is_obj(cmds):
                out.append(f"{w}: commands is required")
            else:
                for k in COMMAND_KEYS:
                    if k not in cmds:
                        out.append(f"{w}: commands.{k} is missing — write the command, or null where the stack has no such step")
                    elif cmds[k] is not None and not isinstance(cmds[k], str):
                        out.append(f"{w}: commands.{k} must be a string or null")
                    elif isinstance(cmds[k], str):
                        check_vars(f"{w} commands.{k}", cmds[k])
                for k in cmds:
                    if k not in COMMAND_KEYS + ["test_fast"]:
                        out.append(f'{w}: unknown command "{k}" (the five, plus optional test_fast for the commit hook)')
                if "test" in cmds and cmds["test"] is None and "test_fast" not in cmds:
                    out.append(f"{w}: has no test command at all — the day-one run would prove nothing")
            files = o.get("files")
            for i, f in enumerate(files if isinstance(files, list) else []):
                fw = f"{w} files[{i}]"
                if (not _is_obj(f) or not isinstance(f.get("to"), str) or f.get("class") not in _FILE_CLASSES
                        or isinstance(f.get("from"), str) == isinstance(f.get("content"), str)):
                    out.append(f"{fw}: needs `to`, a `class` ({'|'.join(_FILE_CLASSES)}) and exactly one of `from` or `content`")
                    continue
                check_vars(f"{fw} to", f["to"])
                # File CONTENT uses [[var]], not {{var}}: Go and Vue templates are full of {{ }}, and a
                # placeholder syntax that collides with the stack's own is one the scaffold would have to
                # escape in every file. [[name]] is substituted only when `name` is a known value; any other
                # [[...]] (a TOML table, a regex class) is left as written, so content is not checked here.
                if re.search(r"^(/|[a-zA-Z]:)|(^|[\\/])\.\.([\\/]|\Z)", f["to"]):
                    out.append(f"{fw}: `to` must stay inside the repo ({f['to']})")
            if not _len(o.get("files")) and not _len(o.get("generator")):
                out.append(f"{w}: has neither a generator nor files, so there is no skeleton")
            if "ci" in o and not (_is_obj(o["ci"]) and o["ci"].get("setup") in CI_SETUPS):
                out.append(f"{w}: ci.setup must be one of {', '.join(CI_SETUPS)}")
    return out


def _reject_constant(name):
    # json.loads accepts NaN/Infinity; JSON.parse (what the manifest was specified against)
    # does not, and a manifest that only one runtime can read is a Gate 3 lock that breaks at G5.
    raise ValueError(f"Unexpected token {name} in JSON")


def check_scaffold(root=".", meta=None):
    """Read and check the scaffold manifest that goes with the selected playbook. `meta` is the
    parsed frontmatter, or None when the playbook mechanism is off (`architecture.playbook: none`)
    and the project wrote adr/scaffold.json itself."""
    res = {"path": None, "manifest": None, "problems": [], "missing": False}
    if meta:
        scaffold = meta.get("scaffold")
        if not scaffold or scaffold.lower() == "none":
            res["problems"].append(
                f"{VENDORED_PLAYBOOK} declares `scaffold: {scaffold or '(absent)'}` — a playbook that cannot scaffold a repo "
                f"fails here, at Gate 3, not at G5 when the first lane needs one. Point `scaffold:` at the playbook's manifest.")
            return res
        res["path"] = VENDORED_SCAFFOLD
    else:
        res["path"] = SCAFFOLD_LOCAL
    file = _join(root, res["path"])
    if not os.path.exists(file):
        res["missing"] = True
        tail = (" — `python3 scripts/playbook.py vendor` copies it beside the playbook" if meta else
                " — with no playbook, the stack ADR is accompanied by a scaffold manifest you write (references/playbooks/README.md)")
        res["problems"].append(f"{res['path']} does not exist{tail}")
        return res
    try:
        res["manifest"] = json.loads(_read_text(file), parse_constant=_reject_constant)
    except ValueError as err:
        res["problems"].append(f"{res['path']} is not valid JSON ({err})")
        return res
    for p in scaffold_problems(res["manifest"]):
        res["problems"].append(f"{res['path']}: {p}")
    return res


def check_playbook(root="."):
    """The whole playbook check, in one call so validate.py and gate.py report identically.
    `problems` are always wrong; `missing_vendored` is normal until `vendor` runs."""
    cfg = read_architecture_config(root)
    vendored_path = _join(root, VENDORED_PLAYBOOK)
    explicit = cfg["playbook"]
    # `none` is the only way to switch the mechanism off: every stack decision blank-slate, the
    # project writing its own scaffold manifest. A blank value is NOT that: it resolves to the org
    # default, which is what `vendor` copies.
    disabled = bool(explicit) and explicit.lower() == "none"
    res = {
        "explicit": explicit,
        "selected": None if disabled else (explicit or DEFAULT_PLAYBOOK),
        "selected_by": "none" if disabled else ("sources.yaml" if explicit else "default"),
        "disabled": disabled,
        "target_shape": cfg["target_shape"],
        "vendored": VENDORED_PLAYBOOK if os.path.exists(vendored_path) else None,
        "meta": None, "problems": [], "missing_vendored": False, "scaffold": None,
    }
    if disabled:
        res["scaffold"] = check_scaffold(root, None)
        return res
    # Absence is reported separately from `problems` because it is legitimate until the stack
    # preference step vendors the copy; gate-3 is where it becomes fatal.
    if not res["vendored"]:
        res["missing_vendored"] = True
        return res
    # `architecture.playbook` may name a registry entry (`mobile-flutter`) or a path to one the
    # user wrote (`playbooks/ours.md`). The vendored file's own `playbook:` is always the bare
    # name, so compare on the bare name or a path-selected playbook reports a mismatch with
    # itself — which would make the user-written case unusable, the case the registry exists for.
    selected_name = re.sub(r"\.md\Z", "", res["selected"], flags=re.I).split("/")[-1]
    vendored_text = _read_text(vendored_path)
    meta = parse_playbook_meta(vendored_text)
    if not meta:
        res["problems"].append(f"{VENDORED_PLAYBOOK} has no frontmatter block — it is not a registry playbook")
        return res
    res["meta"] = meta
    if meta["playbook"] and meta["playbook"] != selected_name:
        res["problems"].append(f'{VENDORED_PLAYBOOK} declares playbook "{meta["playbook"]}" but sources.yaml selects "{res["selected"]}"')
    res["scaffold"] = check_scaffold(root, meta)
    res["problems"].extend(res["scaffold"]["problems"])
    if cfg["target_shape"] and meta["target_shape"] and cfg["target_shape"] != meta["target_shape"]:
        res["problems"].append(
            f'target shape mismatch: sources.yaml says "{cfg["target_shape"]}", '
            f'playbook "{meta["playbook"]}" serves "{meta["target_shape"]}"')

    return res


# One-line remedy, shared so both scripts say the same thing.
PLAYBOOK_REMEDY = (
    f"Before rspec:tech, run `python3 scripts/playbook.py vendor` from the workbench root: it copies the playbook "
    f"sources.yaml's architecture.playbook selects from the plugin's {REGISTRY_DIR}/ to {VENDORED_PLAYBOOK}, with its "
    f"scaffold manifest. With architecture.playbook: none, write {SCAFFOLD_LOCAL} yourself.")


def vendor(root=".", plugin=None):
    """Copy the selected playbook and its scaffold manifest into adr/. Returns (copied paths, problem or None).

    The source is the plugin's registry (a bare name) or a path relative to the workbench (a playbook the user
    wrote). The plugin root is `plugin`, else the one `.rebuild-plugin` records, which is how upgrade.py finds it
    too: an environment variable would outlive a moved plugin silently."""
    res = check_playbook(root)
    if res["disabled"]:
        return [], f"architecture.playbook is none: write {SCAFFOLD_LOCAL} yourself (references/playbooks/README.md)"
    sel = res["selected"]
    if "/" in sel or sel.lower().endswith(".md"):
        src = _join(root, sel)
    else:
        if not plugin:
            marker = _join(root, ".rebuild-plugin")
            lines = ([l.strip() for l in _read_text(marker).split("\n") if l.strip() and not l.startswith("#")]
                     if os.path.exists(marker) else [])
            plugin = lines[0] if lines else None
        if not plugin:
            return [], "no plugin root: pass --plugin <root> (no .rebuild-plugin in this workbench)"
        src = _join(plugin, REGISTRY_DIR, sel + ".md")
    if not os.path.exists(src):
        return [], f"no playbook at {src}"
    text = _read_text(src)
    meta = parse_playbook_meta(text)
    scaffold = (meta or {}).get("scaffold")
    if not scaffold or scaffold.lower() == "none":
        return [], f"{src} declares no `scaffold:` manifest, so no code repo can be created from it"
    manifest = _join(os.path.dirname(src), scaffold)
    if not os.path.exists(manifest):
        return [], f"{src} names scaffold {scaffold}, which does not exist at {manifest}"
    os.makedirs(_join(root, "adr"), exist_ok=True)
    for dst, body in ((VENDORED_PLAYBOOK, text), (VENDORED_SCAFFOLD, _read_text(manifest))):
        with open(_join(root, dst), "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    return [VENDORED_PLAYBOOK, VENDORED_SCAFFOLD], None


def _cli(argv):
    if argv and argv[0] == "vendor":
        copied, why = vendor(".", argv[argv.index("--plugin") + 1] if "--plugin" in argv[:-1] else None)
        if why:
            print(f"playbook.py vendor: {why}", file=sys.stderr)
            return 1
        print(f"vendored {', '.join(copied)}; gate-3 locks adr/ with the ADRs. Commit them.")
        return 0
    print("Usage: playbook.py vendor [--plugin <plugin root>]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
