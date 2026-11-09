#!/usr/bin/env python3
"""gate_status.py (eval) — 2.1.1: does `gate.py status` name the phase a rebuild is really in, and
does Gate 3 refuse ADRs nobody decided?

  python3 skills/rebuild-pipeline/eval/gate_status.py

WHY IT EXISTS. SKILL.md tells the orchestrator to trust `gate.py status` over its memory, so a wrong
phase there routes a session to the wrong work. The Kutt rebuild (2026-11-03) met three cases:
  - its G3 drafter wrote plan/slices.yaml as a JSON array (valid YAML, and the schema's own shape),
    which the block parser read as no slices, so status said "GP production readiness" with no code;
  - a fresh workbench with findings/ empty was told "G2 feature matrix", skipping G1 mining;
  - eleven ADRs reached the Gate 3 lock still saying `status: proposed`.
Each builds a throwaway workbench with rebuild_init.py and checks the answer. From 3.0.0 rspec owns the
stages before gate-1 (no mining phase to name), the slices are rspec's docs/build-plan.md (the next unfinished
one is in coverage_rspec.py) and the ADRs live in rspec's docs/decisions/; the gate order and lock checks
themselves are in gates_rspec.py.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SCRIPTS = os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts")

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if not ok:
        failures += 1
        if detail:
            print("      " + str(detail).replace("\n", "\n      "))


base = tempfile.mkdtemp(prefix="gate-status-eval-")
subprocess.run([sys.executable, os.path.join(SCRIPTS, "rebuild_init.py"), "gs", "--dir", base],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
wb = next(os.path.join(base, d) for d in os.listdir(base) if os.path.exists(os.path.join(base, d, "locks", "pipeline.yaml")))


def write(rel: str, text: str) -> None:
    p = os.path.join(wb, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def phase() -> str:
    r = subprocess.run([sys.executable, os.path.join(wb, "scripts", "gate.py"), "status"], cwd=wb,
                       capture_output=True, text=True, encoding="utf-8")
    m = re.search(r"^Current phase: (.*)$", r.stdout, re.M)
    return m.group(1) if m else r.stdout + r.stderr


def set_locked(*gates: str) -> None:
    for g in gates:
        p = os.path.join(wb, "locks", f"{g}.yaml")
        with open(p, encoding="utf-8") as f:
            text = f.read()
        with open(p, "w", encoding="utf-8") as f:
            f.write(re.sub(r"^status: .*$", "status: locked", text, count=1, flags=re.M))


# --- Before gate-1: rspec's first stages (3.0.0, 05 P2; G1 mining is gone) -----------------------
check("a new workbench is in rspec's first stages, toward gate-1", phase().startswith("rspec init"), phase())

# --- After gate-4: the build, until every slice of rspec's plan is done ------------------------
set_locked("gate-1", "gate-3", "gate-2", "gate-4")
write("docs/build-plan.md", "# Build plan\n\n## Slice 1: a\n\n| 1 | F-AB-01 a |\n\n## Slice 2: b\n\n| 1 | F-AB-02 b |\n")
write("plan/progress.yaml", "slices:\n  S1: done\n\n  S2: deployed\n")
check("every slice done or deployed is GP production readiness", phase().startswith("GP production readiness (2/2"), phase())
write("docs/build-plan.md", "# Build plan\n\nnothing cut yet\n")
check("a build plan with no readable slice says so, not GP",
      phase().startswith("G5 build (docs/build-plan.md has no `## Slice`"), phase())

# --- Gate 3 refuses ADRs still proposed (rspec's docs/decisions/ from 3.0.0) ----------------------
sys.path.insert(0, os.path.join(wb, "scripts"))
os.chdir(wb)
import gate  # noqa: E402

write("docs/decisions/0001-decomposition.md", "# ADR-0001\n\n- Status: Proposed\n")
write("docs/decisions/0002-storage.md", "# ADR-0002\n\n- Status: Accepted\n")
write("docs/decisions/0003-auth.md", "# ADR-0003\n\n**Status:** Rejected\n")
check("an ADR still proposed is named; decided ones are not",
      gate.proposed_adrs() == ["0001-decomposition.md"], gate.proposed_adrs())
write("docs/decisions/0001-decomposition.md", "# ADR-0001\n\n- Status: Accepted\n")
check("all decided: nothing named", gate.proposed_adrs() == [], gate.proposed_adrs())

# --- G0 holds rspec's discovery until preflight says the reference is the pinned one ------------
ref = os.path.join(base, "reference")
os.makedirs(ref)
for cmd in (["git", "init", "-q"], ["git", "-c", "user.email=e@x", "-c", "user.name=e", "commit", "-q", "--allow-empty", "-m", "r"]):
    subprocess.run(cmd, cwd=ref, check=True, capture_output=True)
head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ref, capture_output=True, text=True, check=True).stdout.strip()


def preflight(pinned):
    write("sources.yaml", f"project: gs\nreference:\n  name: ref\n  repo: https://example.invalid/ref.git\n"
                          f"  pinned_commit: {pinned}\n  checkout: {ref.replace(os.sep, '/')}\n  license: MIT\n  kind: third-party\n")
    r = subprocess.run([sys.executable, os.path.join(wb, "scripts", "preflight.py")], cwd=wb, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    with open(os.path.join(wb, "preflight.json"), encoding="utf-8") as f:
        return r.returncode, json.load(f).get("verdict")


check("a checkout at another commit than pinned_commit is Not-ready, exit 1", preflight("0" * 40) == (1, "Not-ready"),
      preflight("0" * 40))
code, verdict = preflight(head)
check("at the pinned commit preflight passes (Ready or Ready-with-gaps)", code == 0 and verdict.startswith("Ready"), verdict)

print("\nall passed" if not failures else f"\n{failures} failed")
sys.exit(1 if failures else 0)
