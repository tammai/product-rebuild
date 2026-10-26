#!/usr/bin/env python3
"""routing.py — resolves which MODEL each pipeline subagent runs on. Run from the workbench root.

Usage:
  python3 scripts/routing.py                     # all seven roles, as JSON
  python3 scripts/routing.py --role miner        # one role
  python3 scripts/routing.py --agents <dir>      # read effort pins from real agent frontmatter

WHY THIS EXISTS

subagent-briefs.md carried the routing rule as prose — "extraction → low tier; merge/spec →
mid; ADR drafting → high" — and the judge brief said "route it to a high tier". Neither had a
mechanism behind it, and the four agent files carried no `model:` at all, so every dispatch
inherited whatever model the orchestrator session happened to be running. The G1 fan-out, the
rubric score at every gate, and every module spec all ran on one model, usually opus, and the
prose rule describing otherwise was true of nothing.

Pinning `model:` in the agent frontmatter fixed the inheritance but replaced it with a
constant: a pin is not a decision a project can make. This script is that decision. It maps
each ROLE to a tier, resolves the tier to a model through the project's chosen ladder, and
prints what the orchestrator passes as `model:` on the Agent call. It is a script and not a
line in a doc because the orchestrator needs one answer it can read, not a table it has to
re-derive from prose on every dispatch.

THE LADDER

Two profiles, `balanced` (default) and `frontier`, over three tiers — worker · architect ·
verifier — each resolving to a model. `balanced` runs volume and verification on sonnet and
reserves opus for architecture, where a wrong call propagates into every slice built on it;
`frontier` also moves the worker tier to opus, for a project whose lanes keep coming back FAIL
or whose miners keep missing rules. A profile is a project decision, so it lives in the
workbench's config, not in an agent file.

What is NOT per-dispatch is the tier assignment. A router could score each task to pick a
tier; here the roles are fixed and so are their tiers, mapped once in ROLE_TIERS by what each
role's errors cost. There is nothing to score.

WHY EFFORT DOES NOT MOVE

Effort cannot be passed at spawn time (the Agent tool has no effort parameter), so it comes
only from the spawned agent file's frontmatter.

This pipeline deliberately does not ship the same agent at several pins. For a FIXED role, the
argument that set its effort is about what its mistakes cost, and that argument does not change
when a project wants cheaper models: a miner's omissions are just as invisible on a tight
budget as on a loose one. So a profile here moves the MODEL and leaves effort where each role's
own reasoning put it. Where the chosen profile's tier effort disagrees with a role's pin, that
shows up in `warnings` rather than silently, and buying the saving back means overriding the
model. Disagreements are EXPECTED and not a problem to fix: under the default `balanced` the
architect tier runs at medium while adr-drafter is pinned high, and under `frontier` the worker
tier runs at medium while miner, rubric-judge, spec-writer and lane-worker are pinned high.

BUILD LANES ARE THIS PLUGIN'S AGENTS

`build-lane` and `lane-verifier` resolve to `lane-worker` and `lane-verifier`, shipped in
agents/ beside the miner and the rest. Until 1.0.0 they were another plugin's agents, and
the effort followed that plugin's profile; they are ordinary roles now, pinned like every
other, with the same warning where the profile disagrees. A role's name and its agent file's
name differ for the lane worker, so ROLE_TIERS carries `agent:` where they do. The config keys
(`build-lane`, `lane-verifier`) are unchanged from 0.x, so a model-routing.json that overrides
either keeps working.

CONFIG

  <workbench>/.claude/model-routing.json
  { "profile": "frontier", "models": { "miner": "haiku", "architect": "fable" } }

`profile` picks a ladder; `models` overrides on top of it and accepts either a TIER key
(worker · architect · verifier) or a ROLE key (miner · rubric-judge · spec-writer · data-model-drafter ·
adr-drafter · build-lane · lane-verifier), with a role key winning over the tier it belongs to. Per-role exists because the
most likely real override in this pipeline is a single role: G1 dispatches miners many at a
time and nothing else in the pipeline fans out like it. Fable is in no profile; it is reachable
only as an override (a tier or role key set to "fable").

There are no aliases for the pre-0.22.0 names. An old profile (`opus-centric`, `lean`) or tier
key (`quick`, `standard`, `deep`) is an unknown value like any other: default plus a warning.

Every malformed input — bad JSON, unknown profile, unknown key, unknown model — degrades to
the default and is listed in `warnings`. This file can never block a dispatch, for the same
reason a bad rubric score can never block a lock: a stalled pipeline is a worse failure than a
wrong-but-visible default. RELAY NON-EMPTY WARNINGS TO THE USER — a config the user believes
is active but is not is worse than no config at all.
"""

import errno
import json
import os
import re
import sys

# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def _read_text(p):
    with open(p, encoding="utf-8", errors="replace", newline="") as f:
        return re.sub(r"\r\n?", "\n", f.read())


CONFIG = ".claude/model-routing.json"
DEFAULT_PROFILE = "balanced"

PROFILES = {
    "balanced": {"worker": "sonnet", "architect": "opus", "verifier": "sonnet"},
    "frontier": {"worker": "opus", "architect": "opus", "verifier": "sonnet"},
}

# Informational only — used to report where a profile's effort disagrees with a role's pin.
PROFILE_EFFORTS = {
    "balanced": {"worker": "high", "architect": "medium", "verifier": "high"},
    "frontier": {"worker": "medium", "architect": "high", "verifier": "high"},
}

MODELS = ["fable", "opus", "sonnet", "haiku"]
TIERS = list(PROFILES[DEFAULT_PROFILE].keys())

# Each role's tier, and WHY that rung — the rationale belongs next to the mapping, because the
# mapping is the only place it is load-bearing.
ROLE_TIERS = {
    "miner": {
        "tier": "worker",
        "why": "extraction against a fixed finding schema, one lane and source per dispatch; the largest fan-out in the pipeline, so it runs on the volume tier. Omissions are the real error, which is why its effort pin stays high.",
    },
    "rubric-judge": {
        "tier": "worker",
        "why": "scoring against a stated rubric; the report is advisory, so a bad score costs a human read rather than a wrong artifact. Omission-hunting is what its high effort pin buys.",
    },
    "spec-writer": {
        "tier": "worker",
        "why": "a module spec's acceptance criteria are what every build lane is held to, but its inputs arrive resolved and it flags what the contracts leave open instead of deciding it. Three blind sonnet-vs-opus runs (comments, workspace, cycles) found no consistent gap in criteria quality or gaps flagged; opus found more cross-contract drift on the one from-scratch module, which a project can buy back with a spec-writer model override. Human review sits between the spec and any code.",
    },
    "adr-drafter": {
        "tier": "architect",
        "why": "architecture decisions, and a wrong structural call propagates into every slice built on it.",
    },
    "data-model-drafter": {
        "tier": "architect",
        "why": "the data model is locked by Gate 4 and every slice builds against it, so a wrong key or a missed ownership boundary is a migration after the lock. It is the same kind of call as an ADR (a structural one), and the drafter is told it may not make a structural change no ADR made. Not A/B tested against a cheaper tier: until 1.4.0 the orchestrator drafted these in its own context, on whatever model the session ran.",
    },
    "build-lane": {
        "tier": "worker",
        "agent": "lane-worker",
        "why": "implementation against a spec the user approved and contracts Gate 4 locked, in a repo whose patterns the scaffold set; the error it makes is the worker kind (didn't check its work), and the joint run and the slice review are what catch that (a lane-verifier audit is available on request). A project whose slices keep failing the joint run moves to the frontier profile.",
    },
    "lane-verifier": {
        "tier": "verifier",
        "why": "the independent audit of a lane's diff against its PLAN.md; a false PASS silently voids the only check between the approved criteria and the code, so it never runs cheaper than the verifier tier.",
    },
}

# Fallback effort pins, used only when the agent files cannot be located. Kept in sync with
# agents/*.md frontmatter; --agents reads the real thing and makes this table irrelevant.
PIN_FALLBACK = {
    "miner": "high",
    "rubric-judge": "high",
    "spec-writer": "high",
    "adr-drafter": "high",
    "data-model-drafter": "high",
    "build-lane": "high",
    "lane-verifier": "high",
}


# The agent file a role dispatches to, which is its own name unless ROLE_TIERS says otherwise.
def _agent_of(role):
    return ROLE_TIERS[role].get("agent", role)


# A config value interpolated into a warning, spelled as the Node original's template string
# spelled it (`null`, `true`, `[object Object]`, 1 for 1.0), so a hand-written config produces the
# same warning text. Absent keys never reach here: they are skipped before.
def _js_str(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        return str(int(v)) if v == int(v) and abs(v) < 1e21 else repr(v)
    if isinstance(v, list):
        return ",".join("" if x is None else _js_str(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


# Node's wording for a failed readdir ("ENOENT: no such file or directory, scandir '<dir>'"),
# because the warning that carries it is relayed to the user and was worded that way.
def _os_error_message(err, syscall, path):
    code = errno.errorcode.get(err.errno, "UNKNOWN")
    text = err.strerror[:1].lower() + err.strerror[1:] if err.strerror else str(err)
    return f"{code}: {text}, {syscall} '{path}'"


# --- effort pins, from the agent files themselves where we can reach them ---

def _read_pins(agents_dir, warnings):
    if not agents_dir:
        return {"pins": dict(PIN_FALLBACK), "source": "fallback-table"}
    try:
        files = sorted(f for f in os.listdir(agents_dir) if f.endswith(".md"))
    except OSError as err:
        warnings.append(f"could not read agents dir {agents_dir} ({_os_error_message(err, 'scandir', agents_dir)}) — using this script's pin table")
        return {"pins": dict(PIN_FALLBACK), "source": "fallback-table"}
    pins = {}
    for f in files:
        agent = re.sub(r"\.md\Z", "", f)
        role = next((r for r in ROLE_TIERS if _agent_of(r) == agent), None)
        if not role:
            continue
        text = _read_text(os.path.join(agents_dir, f))
        fm = re.search(r"^---\n([\s\S]*?)\n---", text)
        effort = fm and re.search(r"^effort:\s*(\S+)\s*$", fm.group(1), re.M)
        if effort:
            pins[role] = effort.group(1)
        else:
            warnings.append(f"{f} declares no effort: — it will run at the model's default")
    for role in ROLE_TIERS:
        if role not in pins:
            warnings.append(f'no agent file found for role "{role}" in {agents_dir} — using this script\'s pin table')
            pins[role] = PIN_FALLBACK[role]
    return {"pins": pins, "source": agents_dir}


# --- config ---

def _default_config():
    return {"profile": DEFAULT_PROFILE, "models": {}, "source": "default"}


def _load_config(root, warnings):
    path = os.path.join(root, CONFIG)
    try:
        raw = _read_text(path)
    except OSError:
        return _default_config()

    try:
        config = json.loads(raw)
    except ValueError as err:
        # Python's parser words its failure differently from V8's: the message in this warning is
        # the one deliberate difference from the Node original.
        warnings.append(f"{CONFIG} is not valid JSON ({err}) — using the {DEFAULT_PROFILE} default")
        return _default_config()
    if not isinstance(config, dict):
        warnings.append(f"{CONFIG} must be a JSON object — using the {DEFAULT_PROFILE} default")
        return _default_config()

    profile = DEFAULT_PROFILE
    if "profile" in config:
        wanted = config["profile"]
        if _js_str(wanted) in PROFILES:
            # Kept as written: `{"profile": ["frontier"]}` indexes the ladder like "frontier" and
            # is echoed back as an array, as the Node original did.
            profile = wanted
        else:
            warnings.append(
                f'unknown profile "{_js_str(wanted)}" in {CONFIG} (known: {", ".join(PROFILES)}) — using {DEFAULT_PROFILE}'
            )

    models = {}
    if "models" in config:
        if not isinstance(config["models"], dict):
            warnings.append(f'{CONFIG} "models" must be an object of key → model — ignored')
        else:
            for key, model in config["models"].items():
                is_tier = key in TIERS
                is_role = key in ROLE_TIERS
                if not is_tier and not is_role:
                    warnings.append(
                        f'unknown key "{key}" in {CONFIG} "models" (tiers: {" · ".join(TIERS)}; roles: {" · ".join(ROLE_TIERS)}) — ignored'
                    )
                    continue
                if not isinstance(model, str) or model not in MODELS:
                    warnings.append(f'unknown model "{_js_str(model)}" for "{key}" in {CONFIG} (known: {" · ".join(MODELS)}) — ignored')
                    continue
                models[key] = model

    if "effort" in config:
        warnings.append(
            f"effort is not settable in {CONFIG} — it comes from the spawned agent's frontmatter and the Agent tool has no effort parameter. See WHY EFFORT DOES NOT MOVE in scripts/routing.py."
        )

    return {"profile": profile, "models": models, "source": "config"}


# --- resolve ---

# The name the Agent tool addresses this plugin's agents by (`<plugin>:<agent>`). Read from the
# plugin's own manifest, which sits beside agents/, so a rename of the plugin cannot leave this
# script dispatching to agents that no longer exist under that name. The fallback is the name
# 1.x ships under, for a run with no agents dir to read it from.
def _read_plugin_name(agents_dir):
    try:
        manifest = json.loads(_read_text(os.path.join(agents_dir, "..", ".claude-plugin", "plugin.json")))
        return manifest["name"] or "product-rebuild"
    except (OSError, ValueError, KeyError, TypeError):
        return "product-rebuild"


def resolve_(root, agents_dir):
    warnings = []
    plugin_name = _read_plugin_name(agents_dir)
    cfg = _load_config(root, warnings)
    profile, models, source = cfg["profile"], cfg["models"], cfg["source"]
    pin_info = _read_pins(agents_dir, warnings)
    pins, pin_source = pin_info["pins"], pin_info["source"]
    ladder = PROFILES[_js_str(profile)]

    roles = {}
    for role, spec in ROLE_TIERS.items():
        tier, why = spec["tier"], spec["why"]
        model = ladder[tier]
        frm = f"profile:{_js_str(profile)}"
        if tier in models:
            model = models[tier]
            frm = f"override:tier:{tier}"
        if role in models:
            model = models[role]
            frm = f"override:role:{role}"

        ladder_effort = PROFILE_EFFORTS[_js_str(profile)][tier]
        effort = pins.get(role)
        agent = f"{plugin_name}:{_agent_of(role)}"

        # Haiku 4.5 accepts no effort level, so a role routed to it runs with its pin inert. Not an
        # error — but on a role whose whole argument for `high` was that its mistakes are omissions,
        # giving up effort control is the thing you would most want said out loud.
        if model == "haiku":
            warnings.append(
                f"{role} resolves to haiku, which accepts no effort level — its effort: {effort} pin is inert on this dispatch."
            )
        if effort != ladder_effort:
            warnings.append(
                f"{role} runs at effort {effort} (its agent file's pin); the {_js_str(profile)} ladder puts the {tier} tier at {ladder_effort}. "
                "Effort is not movable here by design — override the model if you need the saving."
            )

        roles[role] = {"tier": tier, "agent": agent, "model": model, "effort": effort, "modelFrom": frm, "why": why}

    return {"profile": profile, "profileSource": source, "effortSource": pin_source, "roles": roles, "warnings": warnings}


# --- cli ---

def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = sys.argv[1:] if argv is None else list(argv)

    def arg(flag):
        if flag not in argv:
            return None
        i = argv.index(flag)
        return argv[i + 1] if i + 1 < len(argv) else None

    root = arg("--root")
    if root is None:
        root = os.getcwd()
    agents_dir = arg("--agents")
    if agents_dir is None and os.environ.get("CLAUDE_PLUGIN_ROOT"):
        agents_dir = os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], "agents")

    out = resolve_(os.path.abspath(root), os.path.abspath(agents_dir) if agents_dir else None)

    only = arg("--role")
    if only is not None:
        if only not in out["roles"]:
            print(f'unknown role "{only}" — known: {" · ".join(ROLE_TIERS)}', file=sys.stderr)
            return 1
        print(json.dumps({**out, "roles": {only: out["roles"][only]}}, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
