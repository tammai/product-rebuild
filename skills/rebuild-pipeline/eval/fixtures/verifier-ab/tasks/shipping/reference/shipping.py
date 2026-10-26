import math
from fractions import Fraction

BANDS = [(1.0, 510), (2.0, 810), (5.0, 1410), (10.0, 2510), (30.0, 4510)]
ZONES = {"Z1": 0, "Z2": 300, "Z3": 750, "Z4": 1500}


def _hu(num, den):
    return (num * 2 + den) // (den * 2)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _billable(p):
    actual = Fraction(str(p["weight_kg"]))
    dim = Fraction(p["l_cm"] * p["w_cm"] * p["h_cm"], 5000)
    return math.ceil(max(actual, dim) * 2) / 2


def quote(parcels, zone, service="standard", declared_cents=0):
    if not parcels:
        raise ValueError("E-EMPTY")
    if service not in ("standard", "express"):
        raise ValueError("E-SERVICE")
    if zone not in ZONES:
        raise ValueError("E-ZONE")
    if type(declared_cents) is not int or declared_cents < 0:
        raise ValueError("E-DECLARED")
    billable = []
    for p in parcels:
        dims = (p["l_cm"], p["w_cm"], p["h_cm"])
        if not _num(p["weight_kg"]) or p["weight_kg"] <= 0 or any(type(d) is not int or d <= 0 for d in dims):
            raise ValueError("E-PARCEL")
        if p.get("hazmat") and service == "express":
            raise ValueError("E-HAZMAT")
        b = _billable(p)
        if b > 30:
            raise ValueError("E-WEIGHT")
        billable.append(b)
    base = 0
    for b in billable:
        price = next(c for lim, c in BANDS if b <= lim)
        base += price if service == "standard" else _hu(price * 165, 100)
    discount = _hu(base * 5, 100) if len(parcels) >= 3 else 0
    zone_fee = ZONES[zone] * len(parcels)
    if base - discount >= 5020 and zone != "Z4":
        zone_fee = 0
    hazmat = 1200 * sum(1 for p in parcels if p.get("hazmat"))
    fuel_base = base - discount + (0 if zone == "Z4" else zone_fee)
    fuel = _hu(fuel_base * 85, 1000)
    insurance = min(5000, max(150, _hu(declared_cents, 100))) if declared_cents > 0 else 0
    return {"base": base, "discount": discount, "zone_fee": zone_fee, "hazmat": hazmat, "fuel": fuel,
            "insurance": insurance, "total": base - discount + zone_fee + hazmat + fuel + insurance,
            "billable_kg": billable}
