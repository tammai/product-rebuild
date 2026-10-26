#!/usr/bin/env python3
"""prepare.py — one run directory for one drafter dispatch, and its brief.

  python3 prepare.py <concern> <run-name> <out-dir>

The run directory looks like a workbench at G4a as far as the drafter can tell: the vendored playbook
at adr/playbook.md, the drafter's excerpt at plan/adr-excerpts/<concern>.md (cut by the real
`playbook.py excerpt`), and the reference dossier. Ground truth (truth.json) is never copied in.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", "..", ".."))
PB = os.path.join(ROOT, "skills", "rebuild-pipeline", "references", "playbooks", "web-modular-monolith.md")
concern, name, out = sys.argv[1:4]
d = os.path.join(out, "runs", name)
os.makedirs(os.path.join(d, "adr"), exist_ok=True)
os.makedirs(os.path.join(d, "plan", "adr-excerpts"), exist_ok=True)
os.makedirs(os.path.join(d, "reference"), exist_ok=True)
shutil.copy(PB, os.path.join(d, "adr", "playbook.md"))
shutil.copy(os.path.join(HERE, "..", "dossier.md"), os.path.join(d, "reference", "dossier.md"))
ex = subprocess.check_output([sys.executable, os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts", "playbook.py"),
                              "excerpt", concern, "--playbook", PB], text=True)
open(os.path.join(d, "plan", "adr-excerpts", concern + ".md"), "w").write(ex)
meta = subprocess.check_output([sys.executable, "-c", (
    "import sys,json; sys.path.insert(0,%r); import playbook; m=playbook.parse_playbook_meta(open(%r).read()); "
    "print(m['concerns'][%r])") % (os.path.join(ROOT, "skills", "rebuild-pipeline", "scripts"), PB, concern)], text=True).strip()
rules = re.sub(r"\A---\n.*?\n---\n", "", open(os.path.join(ROOT, "agents", "adr-drafter.md")).read(), flags=re.S)
brief = f"""{rules}
---

# Your assignment

You are drafting one ADR in a rebuild workbench at G4a. Work only inside `{d}`.

- Concern key: `{concern}`
- The playbook's `concerns:` map gives this concern: `{meta}`
- Your playbook excerpt: `{d}/plan/adr-excerpts/{concern}.md`
- The vendored playbook (the authority the ADR cites): `{d}/adr/playbook.md`
- The reference product's facts: `{d}/reference/dossier.md` (this is everything you know about the reference;
  there is no source tree to read)
- Output: write the ADR to `{d}/adr/ADR-001-{concern}.md` and nothing else. Status is `proposed`.
- Project shape: `target_shape: fullstack`. No NFR beyond what the dossier states.

Report in at most ~600 characters: the decision value you chose and the path you wrote.
"""
open(os.path.join(out, "briefs", name + ".md"), "w").write(brief) if os.path.isdir(os.path.join(out, "briefs")) else (
    os.makedirs(os.path.join(out, "briefs")) or open(os.path.join(out, "briefs", name + ".md"), "w").write(brief))
print(d)
