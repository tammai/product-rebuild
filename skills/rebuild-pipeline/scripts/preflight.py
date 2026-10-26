#!/usr/bin/env python3
"""preflight.py — prove the reference builds and runs BEFORE G1 dispatches miners.
Run from the workbench root, as the last action of G0.

Usage:
  python3 scripts/preflight.py [--checkout <path>] [--run-build] [--run-tests] [--json]

Writes PREFLIGHT.md (what a human reads) and preflight.json (what autopilot.py and
SKILL.md's phase detection read). Exit 0 on Ready / Ready-with-gaps, 1 on Not-ready.

Standard library only, and sources.yaml is read with the same fixed regex subset gate.py,
pause_check.py and autopilot.py use rather than through yamlio. It has to be a fixed subset: this
runs at the end of G0, and a preflight that depended on a full YAML parse of a hand-edited
sources.yaml could fail at the one moment it exists for, on a file G0 has only just written.

WHY THIS EXISTS. G0's exit criteria said "confirm the user can run the reference
locally" and nothing verified it, so the miners started on a promise. Every lane-D
finding cites `path + pinned_commit`; if the checkout on disk is at a different commit,
every one of those citations is wrong, and nothing downstream can tell — the hashes are
of the finding, not of the thing it describes.

It is a script and not a checklist line because the verdict is a file other scripts read:
autopilot and the orchestrator refuse to dispatch G1 miners until preflight.json says
Ready or Ready-with-gaps, and a prose instruction cannot be refused by anything.

---------------------------------------------------------------------------
WHY THE BUILD IS DETECTED AND NOT RUN BY DEFAULT

The spec says this check "runs the build command from the reference's CI definition".
It detects it always; it EXECUTES it only under --run-build / --run-tests, for two
reasons that are not budget:

  1. A build command lifted from an untrusted reference's CI is arbitrary code from the
     same source E7 just finished hardening the miners against. Reading a planted
     comment is the small version of this problem; running a planted `run:` step is the
     large one. That decision belongs to a human, once, not to every invocation.
  2. Idempotency is an acceptance criterion — two runs on an unchanged tree must produce an
     identical preflight.json. A build is the least idempotent thing in a repository.

Not executing is recorded as a gap, named in PREFLIGHT.md with the exact command to run,
so it reads as "unproven", never as "passed". Ready-with-gaps is the honest verdict for
a reference whose build nobody has watched succeed.
---------------------------------------------------------------------------
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


# CRLF to LF on every text read. With git's core.autocrlf=true (the Windows default) the working
# copy is CRLF, and a pattern with a literal `\n` (`^slices:\n`, `^---\n`) silently matches
# nothing — read as "no such block" rather than an error. Same helper in every script that
# parses text; copied, not imported, because each is vendored and must run alone. See
# playbook.py's read_text for the incident.
def _read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n").replace("\r", "\n")


def _write_text(path, text):
    # newline="\n" so Windows does not turn LF into CRLF in files that are then committed.
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _strip_quotes(v):
    return re.sub(r"^[\"'](.*)[\"']$", r"\1", (v or "").strip())


def _git(cwd, *a):
    try:
        r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _on_path(binary):
    # shutil.which, not `sh -c "command -v"`: there is no /bin/sh to ask on Windows, where the
    # shell line reported every tool as missing. On POSIX the two agree for plain executables,
    # which is all this is asked about (scc, cloc, graphify).
    return shutil.which(binary) is not None


def _run_in_checkout(command, checkout):
    # A shell line on purpose: the command comes from the reference's CI definition and may
    # carry pipes, `&&` and env assignments. `why` mirrors the one-line reason the Node version
    # wrote into preflight.json, so a detail line reads the same whichever script wrote it.
    try:
        r = subprocess.run(["/bin/sh", "-c", command], cwd=checkout, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20 * 60)
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": "spawnSync /bin/sh ETIMEDOUT"}
    except OSError:
        return {"ok": False, "why": "spawnSync /bin/sh ENOENT"}
    if r.returncode == 0:
        return {"ok": True}
    return {"ok": False, "why": f"Command failed: /bin/sh -c {command}".split("\n")[0]}


def _probe(url):
    # Any HTTP status counts as an answer (below 500 is "up"); only a connection that never
    # produced one is a failure. urllib raises on 4xx/5xx, so those are unwrapped here.
    try:
        with urllib.request.urlopen(url, timeout=10) as res:
            return {"ok": res.status < 500, "status": res.status}
    except urllib.error.HTTPError as e:
        return {"ok": e.code < 500, "status": e.code}
    except (TimeoutError, OSError) as e:
        if isinstance(e, TimeoutError) or "timed out" in str(e):
            return {"ok": False, "why": "This operation was aborted"}
        return {"ok": False, "why": "fetch failed"}
    except Exception:
        return {"ok": False, "why": "fetch failed"}


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = list(sys.argv[1:] if argv is None else argv)

    def arg_after(flag):
        if flag not in args:
            return None
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else None

    def has(flag):
        return flag in args

    if not os.path.exists(os.path.join("locks", "pipeline.yaml")):
        print("No locks/pipeline.yaml here — run from the workbench root.", file=sys.stderr)
        return 1

    # --- sources.yaml, fixed subset -----------------------------------------------------
    sources_text = _read_text("sources.yaml") if os.path.exists("sources.yaml") else ""

    def block_field(block, key):
        """A `key:` whose value lives in the two-space-indented block under it."""
        m = re.search(rf"^{block}:\n((?:(?:[ \t]+.*)?\n)*)", sources_text, re.M)
        if not m:
            return ""
        f = re.search(rf"^\s+{key}:\s*(.*)$", m.group(1), re.M)
        return _strip_quotes(re.split(r"\s+#", f.group(1) if f else "")[0])

    def list_under(key):
        m = re.search(rf"^{key}:\n((?:(?:[ \t]+.*)?\n)*)", sources_text, re.M)
        if not m:
            return []
        items = (_strip_quotes(re.split(r"\s+#", x.group(1))[0])
                 for x in re.finditer(r"^\s+- (.*)$", m.group(1), re.M))
        return [i for i in items if i]

    ref = {
        "name": block_field("reference", "name"),
        "repo": block_field("reference", "repo"),
        "pinned_commit": block_field("reference", "pinned_commit"),
        "kind": block_field("reference", "kind"),
        "checkout": block_field("reference", "checkout"),
    }
    allowed = list_under("allowed")

    # --- where the reference checkout is ------------------------------------------------
    # --checkout wins; then sources.yaml's optional `reference.checkout:`; then the two places
    # the pipeline's own instructions put it. Guessing wrong is not a risk worth taking here —
    # a guess that lands on the wrong repo would compare HEAD against an unrelated commit and
    # report Not-ready for a reason that is not true. So the candidates are narrow, and when
    # none of them is a git repo the check fails loudly with the flag to pass.
    checkout_candidates = [c for c in (
        arg_after("--checkout"), ref["checkout"],
        "reference", os.path.normpath(os.path.join("..", "reference")),
        os.path.normpath(os.path.join("..", ref["name"])) if ref["name"] else None,
    ) if c]
    checkout = next((c for c in checkout_candidates if os.path.exists(os.path.join(c, ".git"))), None)

    # --- checks -------------------------------------------------------------------------
    # status: "pass" | "gap" | "fail" | "skip". Only "fail" makes the run Not-ready.
    checks = []

    def add(cid, title, status, detail, effect):
        checks.append({"id": cid, "title": title, "status": status, "detail": detail, "effect": effect})

    # 1. Reference source is at pinned_commit.
    #    Not-ready, and it is the one check that has to be: every lane-D finding cites this
    #    commit, so mining a different tree writes citations that are wrong at the moment they
    #    are written and stay wrong through a gate lock that hashes them.
    title1 = "Reference source is at pinned_commit"
    if not checkout:
        looked = ", ".join(checkout_candidates) or "(nothing to look for — sources.yaml names no reference)"
        add("pinned-commit", title1, "fail",
            f"No reference checkout found. Looked for a .git in: {looked}.",
            "Pass --checkout <path>, or add `checkout:` under `reference:` in sources.yaml.")
    elif not ref["pinned_commit"]:
        add("pinned-commit", title1, "fail",
            f"sources.yaml has no reference.pinned_commit. The checkout at {checkout} is at "
            f"{_git(checkout, 'rev-parse', 'HEAD') or 'an unreadable HEAD'}.",
            "Fill reference.pinned_commit in sources.yaml — every lane-D citation is written against it.")
    else:
        head = _git(checkout, "rev-parse", "HEAD")

        def short(h):
            return (h or "")[:max(7, len(ref["pinned_commit"]))]

        if not head:
            add("pinned-commit", title1, "fail",
                f"Could not read HEAD in {checkout}.", "Is it a git checkout? `git -C <checkout> status`.")
        elif short(head) != short(ref["pinned_commit"]):
            add("pinned-commit", title1, "fail",
                f"{checkout} is at {head[:12]}, sources.yaml pins {ref['pinned_commit']}.",
                "Lane-D evidence would cite the wrong commit. Fix one of the two: "
                f"`git -C {checkout} checkout {ref['pinned_commit']}`, or re-pin sources.yaml to {head[:12]}.")
        else:
            dirty = _git(checkout, "status", "--porcelain")
            if dirty:
                add("pinned-commit", title1, "gap",
                    f"HEAD matches {ref['pinned_commit']}, but the tree has uncommitted changes "
                    f"({len(dirty.split(chr(10)))} path(s)).",
                    "A finding citing path + commit would not reproduce from the commit alone. Clean the checkout.")
            else:
                add("pinned-commit", title1, "pass",
                    f"{checkout} HEAD = {ref['pinned_commit']}, tree clean.", None)

    # 2. + 4. Build and test definitions — detected in the spec's order: CI, then Dockerfile,
    #    then Makefile. First one found wins; the others are still listed, because "the CI says
    #    one thing and the Makefile another" is itself worth knowing before a slice depends on it.
    build_defs, test_defs = [], []
    if checkout:
        wf_dir = os.path.join(checkout, ".github", "workflows")
        if os.path.exists(wf_dir):
            for f in sorted(x for x in os.listdir(wf_dir) if re.search(r"\.ya?ml$", x)):
                body = _read_text(os.path.join(wf_dir, f))
                runs = [r for r in (m.group(1).strip() for m in
                                    re.finditer(r"^\s*(?:- )?run:\s*(?:\||>-?)?\s*(.*)$", body, re.M)) if r]
                # Verb lists, not loose keywords. The first draft used `bundle` as a build verb and
                # `test` as the only test verb, on a reference whose CI reads `bundle exec rake
                # assets:precompile` / `bundle exec rspec`: it reported the Ruby package manager as
                # the build command and found no test suite in a repo that plainly has one. A wrong
                # command here is worse than none — it is what --run-build would execute.
                # re.ASCII: JavaScript's \b is ASCII-only, and a unicode \b would split differently.
                build = next((r for r in runs if re.search(
                    r"\b(build|precompile|compile|assemble|package|dist)\b", r, re.A)), None)
                test = next((r for r in runs if re.search(
                    r"\b(test|tests|spec|rspec|pytest|unittest|jest|vitest|mocha|tox|phpunit|check)\b",
                    r, re.A)), None)
                if build:
                    build_defs.append({"source": f".github/workflows/{f}", "command": build})
                if test:
                    test_defs.append({"source": f".github/workflows/{f}", "command": test})
        if os.path.exists(os.path.join(checkout, "Dockerfile")):
            build_defs.append({"source": "Dockerfile",
                               "command": f"docker build -t {ref['name'] or 'reference'}:preflight ."})
        mk = next((p for p in (os.path.join(checkout, m) for m in ("Makefile", "makefile", "GNUmakefile"))
                   if os.path.exists(p)), None)
        if mk:
            body = _read_text(mk)
            if re.search(r"^build:", body, re.M):
                build_defs.append({"source": os.path.basename(mk), "command": "make build"})
            for t in ("test", "tests", "check"):
                if re.search(rf"^{t}:", body, re.M):
                    test_defs.append({"source": os.path.basename(mk), "command": f"make {t}"})
                    break

    if not checkout:
        add("build", "Reference builds", "skip", "No checkout to inspect.", None)
        add("test-suite", "Reference test suite exists and passes", "skip", "No checkout to inspect.", None)
    elif not build_defs:
        add("build", "Reference builds", "gap",
            "No build definition detected (.github/workflows, Dockerfile, Makefile — in that order).",
            "Lane D still runs; the E8 equivalence lane has no way to stand up the legacy system and stays disabled.")
    elif has("--run-build"):
        d = build_defs[0]
        r = _run_in_checkout(d["command"], checkout)
        outcome = "succeeded" if r["ok"] else f"failed ({r['why']})"
        add("build", "Reference builds", "pass" if r["ok"] else "gap",
            f"{d['source']}: `{d['command']}` — {outcome}.",
            None if r["ok"] else "Lane D still runs; the E8 equivalence lane stays disabled until the reference builds.")
    else:
        d = build_defs[0]
        add("build", "Reference builds", "gap",
            f"Build definition found in {d['source']}: `{d['command']}`. Not executed.",
            "Unproven, not failed. Run it yourself, or re-run: `python3 scripts/preflight.py --run-build` "
            "— that executes a command from the reference's own CI, which is why it is opt-in.")

    title_t = "Reference test suite exists and passes"
    if checkout and not test_defs:
        add("test-suite", title_t, "gap",
            "No test target detected in the reference's CI, Makefile or Dockerfile.",
            "Recorded: the E8 equivalence lane has no baseline to compare against.")
    elif checkout and has("--run-tests"):
        d = test_defs[0]
        r = _run_in_checkout(d["command"], checkout)
        outcome = "passed" if r["ok"] else f"failed ({r['why']})"
        add("test-suite", title_t, "pass" if r["ok"] else "gap",
            f"{d['source']}: `{d['command']}` — {outcome}.",
            None if r["ok"] else "A red reference suite is a baseline fact, not a blocker — record which tests are red before mining.")
    elif checkout:
        d = test_defs[0]
        add("test-suite", title_t, "gap",
            f"Test target found in {d['source']}: `{d['command']}`. Not executed.",
            "Re-run with --run-tests to record the baseline the E8 equivalence lane compares against.")

    # 3. Reference runs. Probe the instance URL from sources.yaml.allowed.
    #    Not-ready for lanes B and C — those two mine the running product and nothing else —
    #    while lane D proceeds, which is why the lane verdicts below are per-lane and the
    #    overall verdict is not simply their minimum.
    instance_urls = [u for u in allowed if re.match(r"^https?://", u)]
    is_mobile = (re.search(r"client-only", block_field("architecture", "target_shape")) is not None
                 and re.search(r"flutter|mobile", block_field("architecture", "playbook"), re.I) is not None)
    if is_mobile:
        # No HTTP endpoint to probe: the running reference is a binary on a device or simulator,
        # and only the user can say whether it is installed and opens. Recorded as a gap the G1
        # exit criteria already make the user confirm, rather than a check this script can fake.
        add("instance", "Reference runs", "gap",
            "Mobile reference: the running instance is the old app on a device or simulator, which this script cannot probe.",
            "Confirm with the user that the old app is installed and opens — ideally from a backup of a real install (g1-mining.md). Lanes B and C depend on it.")
    elif not instance_urls:
        add("instance", "Reference runs", "gap",
            "sources.yaml `allowed:` names no http(s) instance URL to probe.",
            "Lanes B (NFR) and C (UX flows) mine the running product and have nothing to mine. Add the instance URL, or record that the reference cannot be run and accept that B and C are docs-only.")
    else:
        results = [{"url": u, **_probe(u)} for u in instance_urls]
        up = [r for r in results if r["ok"]]
        if not up:
            add("instance", "Reference runs", "gap",
                "; ".join(f"{r['url']} — {('HTTP ' + str(r['status'])) if r.get('status') else r['why']}"
                          for r in results),
                "Lanes B and C have no running product to observe. Lane D may proceed.")
        else:
            add("instance", "Reference runs", "pass",
                "; ".join(f"{r['url']} — HTTP {r['status']}" for r in up), None)

    # 5. Scope boundary — advisory, always. A reference mined at a subdirectory of a larger
    #    repo has siblings that may import from it, and every one of those is behavior the
    #    matrix will not see. Naming them is the whole job; deciding about them is not this
    #    script's call.
    if checkout:
        top = _git(checkout, "rev-parse", "--show-toplevel")
        abs_checkout = os.path.abspath(checkout)
        if top and os.path.abspath(top) != abs_checkout:
            rel = abs_checkout[len(os.path.abspath(top)) + 1:]
            # Either separator: on Windows abspath returns backslashes while git's toplevel
            # arrives with forward slashes, so a "/" split would return the whole path.
            rel_head = re.split(r"[\\/]", rel)[0]
            # sorted(): Node's readdir is alphabetical (libuv sorts), os.listdir is not, and the
            # order of `importers` lands in preflight.json, which must be byte-identical across runs.
            siblings = [d for d in sorted(os.listdir(top))
                        if not d.startswith(".") and d != rel_head and os.path.isdir(os.path.join(top, d))]

            def mentions(d):
                try:
                    r = subprocess.run(["grep", "-rqs", "--", os.path.basename(abs_checkout), os.path.join(top, d)],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    return False
                return r.returncode == 0

            importers = [d for d in siblings if mentions(d)]
            add("scope-boundary", "Scope boundary", "gap",
                f"The mined path is `{rel}` inside the monorepo at {top}. " +
                (f"Sibling(s) mentioning it: {', '.join(importers)}." if importers
                 else "No sibling mentions it by name."),
                "Advisory only. Behavior living in a sibling is behavior the feature matrix will not see — decide deliberately whether it is in scope.")
        else:
            add("scope-boundary", "Scope boundary", "pass", "The checkout is its own repository root.", None)

    # 6. The two G0 interview answers. Recorded in license-posture.md, and they feed
    #    sources.yaml `denied:` — an off-limits path the deny list does not carry is an
    #    instruction that exists only in a conversation nobody will re-read.
    posture = _read_text("license-posture.md") if os.path.exists("license-posture.md") else ""

    # The heading alone does not count — the scaffold ships both headings with a prompt in an
    # HTML comment, so "section present" would pass on an unanswered question, which is the
    # exact failure this check exists to catch. Answered means a line of prose under it.
    def section_body(heading):
        # Split on headings rather than a lookahead: the body runs to the next `## ` or to EOF,
        # and the Node version had no \Z for that second case — an earlier draft wrote one and
        # matched a literal "Z", so the last section of the file silently never matched.
        parts = re.split(r"^## ", posture, flags=re.M)[1:]
        hit = next((p for p in parts if p.split("\n")[0].strip().lower() == heading.lower()), None)
        return None if hit is None else "\n".join(hit.split("\n")[1:])

    def answered(heading):
        body = section_body(heading)
        if body is None:
            return False
        # Strip HTML comments FIRST. The scaffold's prompts span several lines, and a per-line
        # "starts with <!--" test reads the middle line of one as prose — which is a question
        # reported as answered, the one error this check must not make.
        return len(re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()) > 0

    has_prior = answered("Prior attempts")
    has_off_limits = answered("Off-limits")
    if has_prior and has_off_limits:
        add("interview", "Prior attempts and off-limits recorded", "pass",
            "license-posture.md carries both sections.", None)
    else:
        missing = [m for m in ("Prior attempts" if not has_prior else None,
                               "Off-limits" if not has_off_limits else None) if m]
        add("interview", "Prior attempts and off-limits recorded", "gap",
            f"license-posture.md is missing: {', '.join(missing)}.",
            "Ask the two G0 questions (g0-reference.md) and write the answers down. Anything off-limits also belongs in sources.yaml `denied:` — the miners read that, not the prose.")

    # 7. Tooling. Metrics degrade to find/wc without scc/cloc; lane D's miners navigate with
    #    grep instead of a graph without graphify. Both are gaps, neither is fatal.
    counter = next((c for c in ("scc", "cloc") if _on_path(c)), None)
    graphify = _on_path("graphify")
    tool_notes = [
        f"{counter} present" if counter else "neither scc nor cloc on PATH — size metrics fall back to find/wc",
        "graphify present" if graphify else "graphify not on PATH — lane-D miners grep cold instead of querying a graph (g1-mining.md)",
    ]
    add("tooling", "Tooling", "pass" if counter and graphify else "gap", "; ".join(tool_notes),
        None if counter and graphify else "Install what is missing, or accept the degraded path — neither blocks G1.")

    # --- verdict ------------------------------------------------------------------------
    by_id = {c["id"]: c for c in checks}
    failed = [c for c in checks if c["status"] == "fail"]
    gaps = [c for c in checks if c["status"] == "gap"]
    verdict = "Not-ready" if failed else "Ready-with-gaps" if gaps else "Ready"

    # Per-lane, because the causes are not interchangeable: a wrong commit poisons lane D's
    # citations and nothing else; an instance that will not come up takes out B and C and
    # leaves D untouched.
    #
    # A lane verdict is NOT the check's status, and the two must not be collapsed. The spec's
    # row for "reference runs" reads "Not-ready for lanes B and C; lane D may proceed" — but
    # the overall verdict gates dispatch for ALL lanes, so recording that as a global
    # Not-ready would block the one lane the same sentence says may proceed. So an unreachable
    # instance is a global **gap** with lanes B and C **blocked**: the run is Ready-with-gaps,
    # the orchestrator dispatches lane D and lane A, and PREFLIGHT.md says in as many words
    # that B and C have nothing to observe yet.
    #
    # The wrong commit is the only global Not-ready, and it earns it: it is the only cause
    # where dispatching anyway produces artifacts that are wrong rather than missing.
    commit_bad = (by_id.get("pinned-commit") or {}).get("status") == "fail"
    instance_ok = (by_id.get("instance") or {}).get("status") == "pass"
    lanes = {
        "A": "ready",
        "B": "ready" if instance_ok else "blocked",
        "C": "ready" if instance_ok else "blocked",
        "D": "blocked" if commit_bad else "ready",
    }

    # No timestamp in this file, deliberately. Two runs on an unchanged tree must produce a
    # byte-identical preflight.json (it is an acceptance criterion), and a clock makes that
    # impossible. Staleness is answered by the two fields that actually move when the thing
    # being checked moves — `pinned_commit` and `checkout_head`. The human-readable date lives
    # in PREFLIGHT.md, which is prose and has no such contract.
    report = {
        "schema": "preflight.schema.json",
        "verdict": verdict,
        "reference": {
            "name": ref["name"] or None,
            "kind": ref["kind"] or None,
            "pinned_commit": ref["pinned_commit"] or None,
            "checkout": checkout or None,
            "checkout_head": _git(checkout, "rev-parse", "HEAD") if checkout else None,
        },
        "lanes": lanes,
        "checks": checks,
        "blockers": [f"{c['title']}: {c['detail']}" for c in failed],
        "gaps": [f"{c['title']}: {c['detail']}" for c in gaps],
    }
    _write_text("preflight.json", json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    mark = {"pass": "✅", "gap": "🟡", "fail": "⛔", "skip": "—"}
    # JS toISOString(): millisecond precision, literal Z.
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if verdict == "Not-ready":
        banner = ("**G1 dispatch is blocked.** `autopilot preflight` and the orchestrator's G1 step refuse to "
                  "dispatch miners until this reads Ready or Ready-with-gaps. G0's own artifacts — "
                  "`sources.yaml`, `license-posture.md` — commit and push regardless; none of the causes "
                  "below changes a G0 decision.")
    elif verdict == "Ready-with-gaps":
        banner = "**G1 may dispatch.** The gaps below are real and named; each one says what it costs."
    else:
        banner = "**G1 may dispatch.** No gaps."
    check_lines = []
    for c in checks:
        check_lines += [f"### {mark[c['status']]} {c['title']}", "", c["detail"]]
        if c["effect"]:
            check_lines += ["", f"→ {c['effect']}"]
        check_lines.append("")
    md = "\n".join([
        f"# Preflight — {verdict}",
        "",
        f"Generated {generated} by `python3 scripts/preflight.py`. Machine-readable twin: `preflight.json`.",
        "",
        banner,
        "",
        "| Lane | | Verdict |",
        "|---|---|---|",
        f"| A | Features | {lanes['A']} |",
        f"| B | NFR | {lanes['B']} |",
        f"| C | UX flows | {lanes['C']} |",
        f"| D | Ground truth | {lanes['D']} |",
        "",
        "## Checks",
        "",
        *check_lines,
        "## Re-running",
        "",
        "```sh",
        "python3 scripts/preflight.py                           # detect only",
        "python3 scripts/preflight.py --run-build --run-tests   # also execute the reference's own build and test commands",
        "```",
        "",
        "Executing them is opt-in because they are arbitrary commands from a third party's CI —",
        "the same source `agents/miner.md` treats as untrusted input. Detected-not-executed is",
        "recorded as a gap, never as a pass.",
        "",
    ])
    _write_text("PREFLIGHT.md", md)

    if has("--json"):
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1 if verdict == "Not-ready" else 0

    print(f"Preflight: {verdict}\n")
    for c in checks:
        print(f"  {mark[c['status']]} {c['title']}")
        print(f"     {c['detail']}")
        if c["effect"]:
            print(f"     → {c['effect']}")
    print(f"\n  Lanes: A {lanes['A']} · B {lanes['B']} · C {lanes['C']} · D {lanes['D']}")
    print("\nWrote PREFLIGHT.md and preflight.json.")
    if verdict == "Not-ready":
        print("G1 dispatch is blocked until this reads Ready or Ready-with-gaps.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
