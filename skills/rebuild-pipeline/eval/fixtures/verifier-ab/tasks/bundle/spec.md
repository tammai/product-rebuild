# Bundle: shipping quote, coupon engine and leave balances
One lane, three modules at the worktree root: `shipping.py`, `coupons.py` and `leave.py`. Each module is specified below; the criteria are numbered 1 to 33 across all three, and every module is built to its own spec.

## Module 1 — shipping.py
Module `shipping`, file `shipping.py`, Python 3.9+, standard library only.

```python
quote(parcels, zone, service="standard", declared_cents=0) -> dict
```

`parcels` is a list of dicts `{"weight_kg": number, "l_cm": int, "w_cm": int, "h_cm": int, "hazmat": bool}`
(`hazmat` may be missing, meaning False). The result is a dict with these keys, all integer cents except
`billable_kg`: `base`, `discount`, `zone_fee`, `hazmat`, `fuel`, `insurance`, `total`, and `billable_kg`
(a list of floats, one per parcel, in input order). "Half-up" means a value exactly halfway between two
cents rounds up.

**Rate table R1: base price per parcel, by billable weight**

| billable weight (kg) | base (cents) |
|---|---|
| up to and including 1.0 | 510 |
| up to and including 2.0 | 810 |
| up to and including 5.0 | 1410 |
| up to and including 10.0 | 2510 |
| up to and including 30.0 | 4510 |

**Rate table R2: zone fee per parcel (cents):** `Z1` 0, `Z2` 300, `Z3` 750, `Z4` 1500.

### Acceptance criteria (shipping)

1. [R-SHP-001] A parcel's billable weight is the larger of its actual weight and its dimensional weight
   (`l_cm × w_cm × h_cm / 5000`, in kg), rounded UP to the next multiple of 0.5 kg. A value that is already
   a multiple of 0.5 stays as it is. `billable_kg` lists each parcel's billable weight.
2. [R-SHP-002] A parcel's base price comes from table R1 using its billable weight. `base` in the result is
   the sum of the parcels' base prices after the service adjustment in criterion 3.
3. [R-SHP-003] Service `"standard"` leaves each parcel's base price as it is. Service `"express"`
   multiplies each parcel's base price by 1.65, rounded half-up to the cent, per parcel.
4. [R-SHP-004] When the shipment has 3 or more parcels, `discount` is 5% of `base` rounded half-up to the
   cent. Otherwise `discount` is 0. It applies to base prices only, never to zone fees, hazmat fees, fuel
   or insurance.
5. [R-SHP-005] `zone_fee` is the table R2 fee for the zone, times the number of parcels, unless criterion
   10 waives it.
6. [R-SHP-006] `fuel` is 8.5% of the fuel base, rounded half-up to the cent once per shipment. The fuel
   base is `base - discount + zone_fee`, except that in zone `Z4` the zone fee is left out of it. Hazmat
   fees and insurance are never in the fuel base.
7. [R-SHP-007] `insurance`: when `declared_cents` is greater than 0 it is 1% of `declared_cents` rounded
   half-up, but at least 150 and at most 5000. When `declared_cents` is 0 it is 0.
8. [R-SHP-008] Each parcel with `hazmat` true adds a flat 1200 to `hazmat` in the result. Hazmat parcels
   cannot ship `"express"`.
9. [R-SHP-009] Errors are `ValueError` with exactly these messages. An empty `parcels` list: `E-EMPTY`.
   A `service` other than `"standard"` or `"express"`: `E-SERVICE`. A `zone` not in table R2: `E-ZONE`.
   `declared_cents` that is not an integer, or is negative: `E-DECLARED`. A parcel whose weight is not a
   positive number, or any of whose dimensions is not a positive integer: `E-PARCEL`. A hazmat parcel with
   service `"express"`: `E-HAZMAT`. A parcel whose billable weight is over 30: `E-WEIGHT`. Checks run in
   that order. The three parcel checks run parcel by parcel, each parcel's checks in the order
   `E-PARCEL`, `E-HAZMAT`, `E-WEIGHT`, so the first parcel with any problem decides the error.
10. [R-SHP-010] When `base - discount` is at least 5020 and the zone is `Z1`, `Z2` or `Z3`, `zone_fee` is
    0. Zone `Z4` is never waived. A waived zone fee is 0 everywhere it is used, including the fuel base.
11. [R-SHP-011] `total` is `base - discount + zone_fee + hazmat + fuel + insurance`.

## Module 2 — coupons.py
Module `coupons`, file `coupons.py`, Python 3.9+, standard library only.

```python
price_cart(items, coupons, today, usage=None) -> dict
```

`items`: list of `{"sku": str, "category": str, "unit_cents": int, "qty": int}`.
`coupons`: list of dicts with keys `code` (str), `kind` (`"percent"`, `"fixed"` or `"bogo"`), `value` (int;
a percentage for `percent`, cents for `fixed`, unused for `bogo`), `priority` (int), and the optional keys
`scope` (a category name, or None/missing for the whole cart), `min_spend_cents` (missing means 0),
`valid_from` and `valid_to` (ISO dates `"YYYY-MM-DD"`), `group` (str or None), `cap_cents` (int or None),
`per_user_limit` (int or None). `today` is an ISO date string. `usage` maps a coupon code to how many times
this user has already used it (a missing code means 0; `usage` may be None).

The result is `{"subtotal": int, "applied": [{"code": str, "discount": int}, ...], "rejected": {code: reason},
"discount": int, "total": int}`, all money in whole cents. "Half-up" means a value exactly halfway between
two cents rounds up.

### Acceptance criteria (coupons)

12. [R-CPN-001] `subtotal` is the sum over items of `qty × unit_cents`. With no coupons, `total` equals
   `subtotal`, `applied` is empty and `rejected` is an empty dict.
13. [R-CPN-002] Coupons are considered in ascending `priority`, ties broken by `code` in plain string order.
   Each coupon is judged against the cart as the coupons before it left it.
14. [R-CPN-003] A coupon is valid from `valid_from` inclusive until `valid_to` exclusive, comparing the ISO
   date strings with `today`. Before `valid_from` it is rejected with reason `E-NOT-YET`. On or after
   `valid_to` it is rejected with `E-EXPIRED`.
15. [R-CPN-004] When `per_user_limit` is not None and the code's usage count is greater than or equal to it,
   the coupon is rejected with `E-LIMIT`.
16. [R-CPN-005] Coupons that share the same non-None `group` exclude each other: once one coupon of a group
   has been applied, every later coupon of that group is rejected with `E-GROUP`. A coupon that was rejected
   for any reason does not use up its group.
17. [R-CPN-006] A coupon's eligible amount is, for an unscoped coupon, `subtotal` minus the discounts all
   earlier applied coupons gave. For a scoped coupon it is the subtotal of the items whose `category` equals
   its `scope`, minus the discounts earlier applied coupons of that same scope gave. A discount from an
   unscoped coupon never reduces any scope's eligible amount.
18. [R-CPN-007] When the eligible amount is less than `min_spend_cents`, the coupon is rejected with
   `E-MIN-SPEND`. Equal is enough.
19. [R-CPN-008] The raw discount is: for `percent`, `eligible × value / 100` rounded half-up; for `fixed`,
   `value`; for `bogo`, take every unit of the eligible items (the items in scope, or all items for an
   unscoped coupon), each priced at its `unit_cents`, sort the units by price ascending, and the cheapest
   `n // 2` of the `n` units are free, so the discount is the sum of their prices.
20. [R-CPN-009] When `cap_cents` is not None the discount is at most `cap_cents`.
21. [R-CPN-010] Whatever the kind, a coupon's discount is also at most its eligible amount and at most what is
    left of the cart (`subtotal` minus all discounts given so far), so `total` is never below 0. A coupon
    whose final discount is 0 is rejected with `E-NO-EFFECT`. Rejection checks run in this order and the first
    one that fails is the reason: not-yet/expired, `E-LIMIT`, `E-GROUP`, `E-MIN-SPEND`, `E-NO-EFFECT`.
22. [R-CPN-011] `applied` lists the applied coupons in the order they were applied, with each one's final
    discount. `discount` is the sum of those discounts and `total` is `subtotal - discount`. A coupon whose
    `kind` is not one of the three raises `ValueError("E-KIND")`, checked for every coupon in the list before
    anything else is done.

## Module 3 — leave.py
Module `leave`, file `leave.py`, Python 3.9+, standard library only. Dates are ISO strings `"YYYY-MM-DD"`
(zero-padded, 10 characters). Day counts are floats. `holidays` is any collection of ISO date strings.

```python
monthly_rate(tenure_months) -> float
first_month_accrual(join_date) -> float
working_days(start, end, holidays=(), start_half=False, end_half=False) -> float
carry_over(balance) -> (carried: float, forfeited: float)
usable_carry(carried, on_date, year) -> float
request(balance, carry, start, end, holidays=(), manager_ok=False, start_half=False, end_half=False) -> dict
cancel(req, balance, carry, today) -> {"balance": float, "carry": float}
```

### Acceptance criteria (leave)

23. [R-LV-001] `monthly_rate`: tenure of 0 to 11 months accrues 1.0 day a month, 12 to 59 months accrues
   1.25, and 60 months or more accrues 1.75.
24. [R-LV-002] `first_month_accrual(join_date)` is the tenure-0 monthly rate (1.0) times
   `days_remaining / days_in_month`, where `days_remaining` counts the join day through the last day of its
   month, rounded DOWN to a multiple of 0.25. Joining on the 1st gives 1.0.
25. [R-LV-003] `working_days(start, end, holidays)` counts the days from `start` to `end`, both inclusive,
   that fall on Monday to Friday and are not in `holidays`. A holiday on a weekend is not subtracted again.
26. [R-LV-004] With `start_half` true the first day counts 0.5 instead of 1, and with `end_half` true the
   last day counts 0.5. A half-day flag on a day that does not count (weekend or holiday) changes nothing.
   When `start == end`, one flag gives 0.5 on a working day, and both flags together are an error,
   `ValueError("E-HALF")`.
27. [R-LV-005] `carry_over(balance)` carries at most 5.0 days into the new year: a balance of 5.0 or less is
   carried whole, and the part above 5.0 is forfeited. A negative balance is carried whole (the debt carries
   over) and nothing is forfeited. It returns `(carried, forfeited)`.
28. [R-LV-006] Carried days from the previous year can be used through March 31 of `year`, inclusive.
   `usable_carry(carried, on_date, year)` returns `carried` when `on_date` is on or before that date, and
   0.0 after it.
29. [R-LV-007] `request` takes `days = working_days(...)`. Carry is spent first: the carry usable on the
   request's `start` date (`usable_carry(carry, start, start's year)`) covers as many of the days as it can
   (`from_carry`), and the rest comes from `balance` (`from_balance`). `balance_after` is `balance -
   from_balance`. `carry_after` is `carry - from_carry`, or 0.0 when `start` is after March 31 of its year
   (the carry has expired).
30. [R-LV-008] A request that leaves `balance_after` at 0 or more has `status` `"approved"`. One that
   leaves it below 0 but not below -3.0 has status `"needs_approval"` with reason `"E-APPROVAL"`, unless
   `manager_ok` is true, which makes it `"approved"`. One that would leave it below -3.0 has status
   `"denied"` with reason `"E-BALANCE"`, whatever `manager_ok` says. A request that is not approved changes
   nothing: `from_carry` and `from_balance` are 0.0 and `balance_after` and `carry_after` equal the balance
   and carry passed in.
31. [R-LV-009] A request for 0 days (no working days in the range) is `"denied"` with reason
   `"E-NO-WORKDAYS"`, with nothing changed, even when `manager_ok` is true.
32. [R-LV-010] `cancel(req, balance, carry, today)` takes an approved request's result and gives its days
    back. `from_balance` goes back to the balance. `from_carry` goes back to the carry if `today` is on or
    before March 31 of the year of `req["start"]`, and otherwise to the balance. Cancelling a request that
    is not approved raises `ValueError("E-STATE")`.
33. [R-LV-011] A date that is not a valid zero-padded ISO date string raises `ValueError("E-DATE")`.
    `monthly_rate` with a tenure that is negative or not an int raises `ValueError("E-TENURE")`. In
    `working_days` and `request`, `end` before `start` raises `ValueError("E-RANGE")`. Checks run in the
    order `E-DATE` (start, then end), `E-RANGE`, `E-HALF`. A result dict from `request` has the keys
    `status`, `reason` (None when approved), `days`, `from_carry`, `from_balance`, `balance_after`,
    `carry_after` and `start`.
