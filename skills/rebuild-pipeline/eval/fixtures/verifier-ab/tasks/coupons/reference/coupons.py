def _hu(num, den):
    return (num * 2 + den) // (den * 2)


def price_cart(items, coupons, today, usage=None):
    usage = usage or {}
    for c in coupons:
        if c["kind"] not in ("percent", "fixed", "bogo"):
            raise ValueError("E-KIND")
    subtotal = sum(i["qty"] * i["unit_cents"] for i in items)
    applied, rejected, given, scope_given, groups = [], {}, 0, {}, set()
    for c in sorted(coupons, key=lambda c: (c["priority"], c["code"])):
        code = c["code"]
        if today < c["valid_from"]:
            rejected[code] = "E-NOT-YET"
            continue
        if today >= c["valid_to"]:
            rejected[code] = "E-EXPIRED"
            continue
        lim = c.get("per_user_limit")
        if lim is not None and usage.get(code, 0) >= lim:
            rejected[code] = "E-LIMIT"
            continue
        g = c.get("group")
        if g is not None and g in groups:
            rejected[code] = "E-GROUP"
            continue
        scope = c.get("scope")
        if scope is None:
            elig_items = items
            eligible = subtotal - given
        else:
            elig_items = [i for i in items if i["category"] == scope]
            eligible = sum(i["qty"] * i["unit_cents"] for i in elig_items) - scope_given.get(scope, 0)
        if eligible < (c.get("min_spend_cents") or 0):
            rejected[code] = "E-MIN-SPEND"
            continue
        if c["kind"] == "percent":
            d = _hu(eligible * c["value"], 100)
        elif c["kind"] == "fixed":
            d = c["value"]
        else:
            units = sorted(i["unit_cents"] for i in elig_items for _ in range(i["qty"]))
            d = sum(units[: len(units) // 2])
        if c.get("cap_cents") is not None:
            d = min(d, c["cap_cents"])
        d = min(d, eligible, subtotal - given)
        if d <= 0:
            rejected[code] = "E-NO-EFFECT"
            continue
        applied.append({"code": code, "discount": d})
        given += d
        if scope is not None:
            scope_given[scope] = scope_given.get(scope, 0) + d
        if g is not None:
            groups.add(g)
    return {"subtotal": subtotal, "applied": applied, "rejected": rejected, "discount": given,
            "total": subtotal - given}
