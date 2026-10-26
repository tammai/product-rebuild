#!/usr/bin/env python3
"""validate_fixtures.py — prove the hidden tests can tell a right implementation from a wrong one.

  python3 validate_fixtures.py

A scoring eval is only as good as its tests, so before any arm runs: the reference solution must
pass every criterion, and each mutant (one plausible wrong reading of the spec, the kind the traps
are built from) must fail the criterion it is aimed at. A criterion no mutant can fail is untested.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import score  # noqa: E402

TASKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tasks")

M = {
    "invoice": ("invoice.py", [
        ("ac1", 'amounts = [l["qty"] * l["unit_cents"] for l in lines]', 'amounts = [l["unit_cents"] for l in lines]'),
        ("ac2", "subtotal >= 5000", "subtotal > 5000"),
        ("ac2", "return (num * 2 + den) // (den * 2)", "return round(num / den)"),
        ("ac2", 'discount_code == "SAVE10"', 'str(discount_code).upper() == "SAVE10"'),
        ("ac3", "return (num * 2 + den) // (den * 2)", "return round(num / den)"),
        ("ac3", "tax += _half_up((a - d) * RATES[region], 100)", "tax += (a - d) * RATES[region]"),
        ("ac3", "_half_up((a - d) * RATES[region], 100)", "_half_up(a * RATES[region], 100)"),
        ("ac3", 'RATES = {"US": 7, "EU": 20, "JP": 10}', 'RATES = {"US": 7, "EU": 20, "JP": 8}'),
        ("ac4", "subtotal - discount + tax", "subtotal + tax"),
        ("ac5", '"E-REGION"', '"E-REG"'),
        ("ac5", "region not in RATES", "region.upper() not in RATES"),
        ("ac6", 'if not lines:\n        raise ValueError("E-EMPTY")',
         'if region not in RATES:\n        raise ValueError("E-REGION")\n    if not lines:\n        raise ValueError("E-EMPTY")'),
        ("ac6", "type(q) is not int or q <= 0", "q <= 0"),
    ]),
    "ratelimit": ("ratelimit.py", [
        ("ac1", "t + self._window > now", "t + self._window >= now"),
        ("ac1", "t + self._window > now", "t > now - self._window - 1"),
        ("ac2", "math.ceil(", "round("),
        ("ac2", "max(1, math.ceil(hits[0] + self._window - now))", "int(hits[0] + self._window - now)"),
        ("ac2", "hits[0] + self._window - now", "hits[-1] + self._window - now"),
        ("ac3", "return (True, 0)", "return (True, None)"),
        ("ac4", "        self._hits[key] = hits\n        return (False,", "        hits.append(now)\n        self._hits[key] = hits\n        return (False,"),
        ("ac5", "self._hits.pop(key, None)", "pass"),
        ("ac5", "self._hits.pop(key, None)", "self._hits.pop(key)"),
        ("ac6", "limit <= 0", "limit < 0"),
        ("ac6", "or window <= 0", "or window < 0"),
    ]),
    "subscription": ("subscription.py", [
        ("ac1", "day >= self._paid:", "day > self._paid:"),
        ("ac2", "day - self._failed >= self.GRACE_DAYS", "day - self._failed > self.GRACE_DAYS"),
        ("ac2", "if self._state != \"active\":\n            raise ValueError(\"E-TRANSITION\")\n        self._state, self._failed",
         "if self._state not in (\"active\", \"trial\"):\n            raise ValueError(\"E-TRANSITION\")\n        self._state, self._failed"),
        ("ac3", 'self._state = "active"\n        elif', 'self._state = "active"\n            self._paid = day\n        elif'),
        ("ac3", "        elif self._state != \"active\":\n            raise ValueError(\"E-TRANSITION\")\n\n    def cancel", "\n    def cancel"),
        ("ac4", "self._cancel_at = self._period_end(day)", "self._cancel_at = day"),
        ("ac4", 'if self._state in ("trial", "past_due"):', 'if self._state == "trial":'),
        ("ac5", "(new_plan_cents - self.plan_cents) * (self._period_end(day) - day) // self.period_days",
         "round((new_plan_cents - self.plan_cents) * (self._period_end(day) - day) / self.period_days)"),
        ("ac5", "(self._period_end(day) - day)", "(self._period_end(day) - day - 1)"),
        ("ac6", "        else:\n            raise ValueError(\"E-TRANSITION\")\n\n    def upgrade", "        else:\n            pass\n\n    def upgrade"),
    ]),
    "shipping": ("shipping.py", [
        ("ac1", "math.ceil(max(actual, dim) * 2) / 2", "round(max(actual, dim) * 2) / 2"),
        ("ac1", "max(actual, dim)", "actual"),
        ("ac2", "b <= lim", "b < lim"),
        ("ac3", "_hu(price * 165, 100)", "round(price * 1.65)"),
        ("ac4", "len(parcels) >= 3", "len(parcels) > 3"),
        ("ac4", "_hu(base * 5, 100)", "base * 5 // 100"),
        ("ac5", "ZONES[zone] * len(parcels)", "ZONES[zone]"),
        ("ac6", '0 if zone == "Z4" else zone_fee', "zone_fee"),
        ("ac6", "_hu(fuel_base * 85, 1000)", "fuel_base * 85 // 1000"),
        ("ac7", "min(5000, max(150, _hu(declared_cents, 100)))", "max(150, _hu(declared_cents, 100))"),
        ("ac7", "_hu(declared_cents, 100)", "declared_cents // 100"),
        ("ac8", "1200 * sum(", "1000 * sum("),
        ("ac9", "type(declared_cents) is not int or declared_cents < 0", "declared_cents < 0"),
        ("ac9", '''        if p.get("hazmat") and service == "express":
            raise ValueError("E-HAZMAT")
        b = _billable(p)
        if b > 30:
            raise ValueError("E-WEIGHT")''', '''        b = _billable(p)
        if b > 30:
            raise ValueError("E-WEIGHT")
        if p.get("hazmat") and service == "express":
            raise ValueError("E-HAZMAT")'''),
        ("ac10", "base - discount >= 5020", "base - discount > 5020"),
        ("ac10", ' and zone != "Z4":', ":"),
        ("ac11", '"total": base - discount + zone_fee + hazmat + fuel + insurance,', '"total": base - discount + zone_fee + fuel + insurance,'),
    ]),
    "coupons": ("coupons.py", [
        ("ac1", 'subtotal = sum(i["qty"] * i["unit_cents"] for i in items)', 'subtotal = sum(i["unit_cents"] for i in items)'),
        ("ac2", 'key=lambda c: (c["priority"], c["code"])', 'key=lambda c: (c["code"], c["priority"])'),
        ("ac2", 'key=lambda c: (c["priority"], c["code"])', 'key=lambda c: (str(c["priority"]), c["code"])'),
        ("ac3", 'today < c["valid_from"]', 'today <= c["valid_from"]'),
        ("ac3", 'today >= c["valid_to"]', 'today > c["valid_to"]'),
        ("ac4", "usage.get(code, 0) >= lim", "usage.get(code, 0) > lim"),
        ("ac5", "g in groups", "False"),
        ("ac6", "eligible = subtotal - given", "eligible = subtotal"),
        ("ac6", " - scope_given.get(scope, 0)", " - given"),
        ("ac7", '< (c.get("min_spend_cents") or 0)', '<= (c.get("min_spend_cents") or 0)'),
        ("ac8", "_hu(eligible * c[\"value\"], 100)", 'eligible * c["value"] // 100'),
        ("ac8", "units[: len(units) // 2]", "units[len(units) // 2:]"),
        ("ac9", 'd = min(d, c["cap_cents"])', "d = d"),
        ("ac10", "d = min(d, eligible, subtotal - given)", "d = min(d, subtotal - given)"),
        ("ac10", "d = min(d, eligible, subtotal - given)", "d = min(d, eligible)"),
        ("ac10", "if d <= 0:", "if d < 0:"),
        ("ac11", 'if c["kind"] not in ("percent", "fixed", "bogo"):', "if False:"),
        ("ac11", '"total": subtotal - given', '"total": subtotal'),
    ]),
    "leave": ("leave.py", [
        ("ac1", "m < 12", "m <= 12"),
        ("ac1", "m < 60", "m <= 60"),
        ("ac2", "math.floor(Fraction(dim - d.day + 1, dim) * 4) / 4", "round(float(Fraction(dim - d.day + 1, dim)) * 4) / 4"),
        ("ac2", "dim - d.day + 1", "dim - d.day"),
        ("ac3", "day.weekday() < 5", "day.weekday() < 6"),
        ("ac3", "while day <= e:", "while day < e:"),
        ("ac4", "(day == s and start_half) or (day == e and end_half)", "(day == s and start_half)"),
        ("ac4", "if s == e and start_half and end_half:", "if False:"),
        ("ac5", "min(balance, 5.0)", "min(balance, 6.0)"),
        ("ac5", "return (float(balance), 0.0)", "return (0.0, 0.0)"),
        ("ac6", "<= datetime.date(year, 3, 31) else 0.0", "< datetime.date(year, 3, 31) else 0.0"),
        ("ac7", "fc = min(usable_carry(carry, start, year), days)", "fc = 0.0"),
        ("ac7", "carry_after = 0.0 if _d(start) > datetime.date(year, 3, 31) else carry - fc", "carry_after = carry - fc"),
        ("ac8", "after < -3.0", "after <= -3.0"),
        ("ac8", "after < 0 and not manager_ok", "after < 0 and False"),
        ("ac8", 'return out("needs_approval", "E-APPROVAL")', 'return out("needs_approval", "E-APPROVAL", fc, fb, after)'),
        ("ac9", "if days == 0:", "if days < 0:"),
        ("ac10", "if _d(today) <= datetime.date(year, 3, 31):", "if _d(today) < datetime.date(year, 3, 31):"),
        ("ac10", 'if req["status"] != "approved":', "if False:"),
        ("ac11", '"carry_after": float(carry if car is None else car), "start": start}', '"carry_after": float(carry if car is None else car)}'),
        ("ac11", 'raise ValueError("E-TENURE")', 'raise ValueError("E-TEN")'),
    ]),
}

bad = 0
for task, (fname, mutants) in M.items():
    ref = open(os.path.join(TASKS, task, "reference", fname)).read()
    d = tempfile.mkdtemp()
    open(os.path.join(d, fname), "w").write(ref)
    r = score(task, d)
    ok = r["total"] > 0 and r["passed"] == r["total"]
    print(f"{'ok  ' if ok else 'FAIL'}  {task}: reference passes {r['passed']}/{r['total']} criteria ({r.get('tests_total')} tests)")
    bad += 0 if ok else 1
    killed = set()
    for ac, old, new in mutants:
        if old not in ref:
            print(f"FAIL  {task}: mutant pattern not in reference: {old[:50]!r}")
            bad += 1
            continue
        open(os.path.join(d, fname), "w").write(ref.replace(old, new, 1))
        s = score(task, d)
        dead = s["criteria"].get(ac, {}).get("ok") is False or bool(s.get("error"))
        print(f"{'ok  ' if dead else 'FAIL'}  {task}/{ac}: mutant {new[:48]!r} {'fails it' if dead else 'SURVIVES'}")
        bad += 0 if dead else 1
        if dead:
            killed.add(ac)
    for ac in sorted(set(r["criteria"])):
        if ac not in killed:
            print(f"FAIL  {task}/{ac}: no mutant kills it")
            bad += 1
    shutil.rmtree(d)
print("\nall passed" if not bad else f"\n{bad} problem(s)")
sys.exit(1 if bad else 0)
