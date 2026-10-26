#!/usr/bin/env python3
"""score.py — run a task's hidden tests against a run directory; print per-criterion results as JSON.

  python3 score.py <task> <run-dir>

The hidden tests live in tasks/<task>/hidden_test.py, outside every run directory, so no arm's agent
can read them. Each test name carries its criterion (`test_ac3_...`), and the score is the share of
criteria whose tests all pass: a criterion implemented almost right counts as wrong, which is the
failure this eval is about. Runs in a subprocess with a timeout so a hung implementation scores zero
instead of hanging the eval.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

RUNNER = r"""
import importlib.util, json, sys, unittest
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location("hidden_test", sys.argv[2])
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except Exception as e:
    print(json.dumps({"import_error": f"{type(e).__name__}: {e}"})); sys.exit(0)
out = {}
class R(unittest.TextTestResult):
    def _rec(self, test, ok):
        out[test._testMethodName] = ok
    def addSuccess(self, t): super().addSuccess(t); self._rec(t, True)
    def addFailure(self, t, e): super().addFailure(t, e); self._rec(t, False)
    def addError(self, t, e): super().addError(t, e); self._rec(t, False)
suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
unittest.TextTestRunner(stream=open("/dev/null", "w"), resultclass=R).run(suite)
print(json.dumps(out))
"""


def score(task, run_dir, timeout=60):
    hidden = os.path.join(HERE, "..", "tasks", task, "hidden_test.py")
    try:
        p = subprocess.run([sys.executable, "-B", "-c", RUNNER, os.path.abspath(run_dir), os.path.abspath(hidden)],
                           capture_output=True, text=True, timeout=timeout, cwd=run_dir)
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:  # timeout, crash, or no output: nothing passed
        return {"error": f"{type(e).__name__}: {e}", "criteria": {}, "passed": 0, "total": 0}
    if "import_error" in res:
        return {"error": res["import_error"], "criteria": {}, "passed": 0, "total": 0}
    crit = {}
    for name, ok in res.items():
        ac = re.match(r"test_(ac\d+)_", name).group(1)
        c = crit.setdefault(ac, {"tests": 0, "passed": 0})
        c["tests"] += 1
        c["passed"] += 1 if ok else 0
    for c in crit.values():
        c["ok"] = c["passed"] == c["tests"]
    return {"criteria": crit, "passed": sum(1 for c in crit.values() if c["ok"]), "total": len(crit),
            "tests_passed": sum(c["passed"] for c in crit.values()), "tests_total": sum(c["tests"] for c in crit.values())}


if __name__ == "__main__":
    print(json.dumps(score(sys.argv[1], sys.argv[2]), indent=2))
