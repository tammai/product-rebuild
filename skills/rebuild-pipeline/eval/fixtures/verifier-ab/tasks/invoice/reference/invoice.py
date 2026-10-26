RATES = {"US": 7, "EU": 20, "JP": 10}


def _half_up(num, den):
    return (num * 2 + den) // (den * 2)


def compute_invoice(lines, discount_code=None, region="US"):
    if not lines:
        raise ValueError("E-EMPTY")
    for line in lines:
        q = line["qty"]
        if type(q) is not int or q <= 0:
            raise ValueError("E-QTY")
    if region not in RATES:
        raise ValueError("E-REGION")
    amounts = [l["qty"] * l["unit_cents"] for l in lines]
    subtotal = sum(amounts)
    apply = discount_code == "SAVE10" and subtotal >= 5000
    discount = tax = 0
    for a in amounts:
        d = _half_up(a * 10, 100) if apply else 0
        discount += d
        tax += _half_up((a - d) * RATES[region], 100)
    return {"subtotal": subtotal, "discount": discount, "tax": tax, "total": subtotal - discount + tax}
