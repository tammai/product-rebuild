#!/usr/bin/env python3
"""playbook.py — architecture-playbook checks shared by validate.py and gate.py.
Library, not an entry point.

Standard library only by necessity: gate.py runs with nothing but its sibling scripts present,
same constraint as erd.py. So the formats this file reads are parsed by line, not by yamlio, and
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

# Every file this module reads is hand-edited, and one of them will be edited on Windows.
# Splitting a CRLF file on "\n" leaves a `\r` on every line, and a `.` does not match it in the
# Node twin (it is a line terminator there), so a `(.*)$` pattern failed on every *value* line
# while the block *header* still matched — the mechanism then reported "no playbook selected"
# rather than "unparsable", and every check silently switched off. A review reproduced a
# gate-3 lock carrying a fabricated `§999` citation that way, from a CRLF `sources.yaml`
# whose LF twin refused correctly. Normalize once at every read instead of trusting each
# pattern to be CRLF-safe: `read_adrs` happened to use `re.M` and was fine, which is exactly
# what made the inconsistency invisible.
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


# Where G4a vendors the selected playbook. Inside gate-3's `protects:` (`adr/`) on purpose.
VENDORED_PLAYBOOK = "adr/playbook.md"

# Where G4a vendors the playbook's scaffold manifest, beside it and for the same reason: a
# lock that hashes the ADRs but not the stack they chose would let the scaffold drift from
# what Gate 3 approved. With `architecture.playbook: none` there is no registry manifest, so
# the project writes its own at SCAFFOLD_LOCAL — same format, same checks, same lock.
VENDORED_SCAFFOLD = "adr/playbook.scaffold.json"
SCAFFOLD_LOCAL = "adr/scaffold.json"

# Registry path inside the plugin, for messages only — the workbench never reads it.
REGISTRY_DIR = "skills/rebuild-pipeline/references/playbooks"

# The playbook a project gets when `sources.yaml` names none. This is not a convenience
# default: `g4a-architecture.md` step 0.1 and `docs/PLAYBOOK.md` both say an absent or empty
# `architecture.playbook` resolves here and step 0.3 then vendors it, so treating the blank
# scaffolded value as "no playbook, run no checks" left the *most common* configuration
# unenforced while three documents claimed otherwise.
DEFAULT_PLAYBOOK = "web-modular-monolith"


def is_pre_playbook_workbench(root="."):
    """True for workbenches scaffolded before the playbook registry existed. They get warnings
    where a new workbench gets errors. Same signal and same reasoning as
    `erd.is_legacy_workbench`: `locks/pipeline.yaml`'s schema_version, because `protects:`
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


def playbook_sections(text):
    """Section numbers the playbook actually declares, read from its own headings
    (`## 4. Backend`, `### 4.2 Hard Rules for Feature Boundaries`).

    This exists because the `concerns:` map answers "which section covers this concern" and is
    NOT the list of sections that exist. Seeding the citation check from the map alone rejected
    an ADR citing a real section no concern happens to map (§15 Testing Strategy, §19
    Anti-patterns) and — worse — a *subsection* of a mapped one: `mobile-flutter.md` maps
    `decomposition: "§2, §4, §20"` and has a `### 4.3` that is the natural thing for that
    ADR to cite. Both were reported as "the wrong playbook", which is a false accusation."""
    out = set()
    for m in re.finditer(r"^#{2,6}\s+([0-9]+(?:\.[0-9]+)*)[.):]?(?=\s)", _strip_cr(text), re.M):
        out.add("§" + m.group(1))
    return out


def cited_sections(meta):
    """Section tokens a playbook's concerns map cites — where each concern's answer lives."""
    out = set()
    for v in ((meta or {}).get("concerns") or {}).values():
        for tok in re.findall(r"§\s*[A-Za-z0-9_.]+", _js_str(v)):
            out.add(re.sub(r"\s+", "", tok))
    return out


_ADR_NON_ADR = {"playbook.md", "README.md", "readme.md"}


def read_adrs(root="."):
    """Every ADR in adr/, with the two fields the playbook mechanism reads."""
    d = _join(root, "adr")
    if not os.path.exists(d):
        return []
    out = []
    for f in sorted(_join(d, n) for n in os.listdir(d)
                    if n.endswith(".md") and n not in _ADR_NON_ADR):
        if not os.path.isfile(f):
            continue
        text = _read_text(f)
        concern = re.search(r"^concern:\s*(.+)$", text, re.M)
        org_default = re.search(r"^org-default:\s*(.+)$", text, re.M)
        out.append({
            "file": f,
            "concern": _unquote(concern.group(1)) if concern else None,
            "org_default": _unquote(org_default.group(1)) if org_default else None,
        })
    return out


# The scaffold manifest contract. scaffold-repo reads the same file through this module, so what
# Gate 3 accepts is exactly what G5 can run. See references/playbooks/README.md for the format.
COMMAND_KEYS = ["install", "build", "lint", "typecheck", "test"]
# Generic rule seeds scaffold-repo ships in skills/scaffold-repo/templates/rules/.
RULE_SEEDS = ["code-style", "tests", "migrations", "sensitive", "ci"]
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
    known = ["ask", "ci", "rules", "packages"]
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

    rules = m.get("rules")
    for r in (rules if isinstance(rules, list) else []):
        if not (isinstance(r, str) and r in RULE_SEEDS):
            out.append(f'rules: "{_js_str(r)}" is not a shipped seed ({", ".join(RULE_SEEDS)})')
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
        tail = (" — G4a step 0.3 vendors it beside the playbook" if meta else
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

    `problems` are always wrong. `undecided` is a list of concerns with no ADR — legitimate
    until Gate 3 is about to lock, so it is returned separately and callers decide when it
    becomes fatal. Same split as erd.check_data_model's `missing`."""
    cfg = read_architecture_config(root)
    vendored_path = _join(root, VENDORED_PLAYBOOK)
    explicit = cfg["playbook"]
    # `none` is the only way to switch the mechanism off — G4a step 0b, every ADR blank-slate.
    # A blank value is NOT that: it resolves to the org default, which is what G4a vendors.
    disabled = bool(explicit) and explicit.lower() == "none"
    res = {
        "explicit": explicit,
        "selected": None if disabled else (explicit or DEFAULT_PLAYBOOK),
        "selected_by": "none" if disabled else ("sources.yaml" if explicit else "default"),
        "disabled": disabled,
        "target_shape": cfg["target_shape"],
        "vendored": VENDORED_PLAYBOOK if os.path.exists(vendored_path) else None,
        "meta": None, "problems": [], "missing_vendored": False, "undecided": [],
        "adrs": read_adrs(root), "scaffold": None,
    }
    if disabled:
        res["scaffold"] = check_scaffold(root, None)
        return res
    # Absence is reported separately from `problems` because it is legitimate for most of a
    # project's life: G4a vendors the copy, and everything before G4a validates without it.
    # Callers decide when it becomes fatal — same split as `erd.check_data_model`'s `missing`.
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
    if not meta["concerns"]:
        res["problems"].append(f"{VENDORED_PLAYBOOK} declares no concerns: map — G4a has nothing to walk")
    res["scaffold"] = check_scaffold(root, meta)
    res["problems"].extend(res["scaffold"]["problems"])
    if cfg["target_shape"] and meta["target_shape"] and cfg["target_shape"] != meta["target_shape"]:
        res["problems"].append(
            f'target shape mismatch: sources.yaml says "{cfg["target_shape"]}", '
            f'playbook "{meta["playbook"]}" serves "{meta["target_shape"]}"')

    # Legal citations = the sections the map points at, PLUS every section the playbook
    # actually declares. See `playbook_sections` for why the map alone is the wrong authority.
    legal = cited_sections(meta) | playbook_sections(vendored_text)

    def section_is_known(tok):
        # A subsection of a real section is real: `§4.2.1` is satisfied by a known `§4.2` or `§4`.
        parts = re.sub(r"\A§", "", tok).split(".")
        for n in range(len(parts), 0, -1):
            if "§" + ".".join(parts[:n]) in legal:
                return True
        return False

    decided = set()
    for adr in res["adrs"]:
        if not adr["concern"]:
            res["problems"].append(f"{adr['file']}: no `concern:` field — cannot tell which playbook concern it decides")
            continue
        decided.add(adr["concern"])
        if adr["concern"] not in meta["concerns"]:
            res["problems"].append(f'{adr["file"]}: concern "{adr["concern"]}" is not in {VENDORED_PLAYBOOK}\'s concerns map')
        if not adr["org_default"]:
            res["problems"].append(f"{adr['file']}: no `org-default:` field (use N/A for a concern with no default)")
            continue
        # `n/a\b` not `n/a$`: the ADR template presents this field as
        # "<cited section(s) …, or N/A where it has no answer>", so a drafter writing
        # `N/A — the reference schema is the only axis` is the expected output, not a deviation.
        # `\b` still rejects `N/Applicable`, which is not this field's vocabulary.
        if re.match(r"n/a\b", adr["org_default"], re.I | re.A):
            continue
        cited = [re.sub(r"\s+", "", t) for t in re.findall(r"§\s*[A-Za-z0-9_.]+", adr["org_default"])]
        if not cited:
            res["problems"].append(f'{adr["file"]}: org-default "{adr["org_default"]}" cites no § section and is not N/A')
            continue
        for tok in cited:
            if not section_is_known(tok):
                res["problems"].append(
                    f"{adr['file']}: org-default cites {tok}, which {VENDORED_PLAYBOOK} "
                    f"has no such section for (checked against its headings and its concerns map) — "
                    f"a stale citation, or the wrong playbook")
    for concern in meta["concerns"]:
        if concern not in decided:
            res["undecided"].append(concern)
    return res


# One-line remedy, shared so both scripts say the same thing.
PLAYBOOK_REMEDY = (
    f"At G4a entry, copy the playbook named by sources.yaml's architecture.playbook from the "
    f"plugin's {REGISTRY_DIR}/ to {VENDORED_PLAYBOOK}, then draft one ADR per concern in its "
    f"concerns: map, each declaring `concern:` and `org-default:` (see references/g4a-architecture.md).")
