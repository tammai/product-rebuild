# Coupon engine

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

## Acceptance criteria

1. [R-CPN-001] `subtotal` is the sum over items of `qty × unit_cents`. With no coupons, `total` equals
   `subtotal`, `applied` is empty and `rejected` is an empty dict.
2. [R-CPN-002] Coupons are considered in ascending `priority`, ties broken by `code` in plain string order.
   Each coupon is judged against the cart as the coupons before it left it.
3. [R-CPN-003] A coupon is valid from `valid_from` inclusive until `valid_to` exclusive, comparing the ISO
   date strings with `today`. Before `valid_from` it is rejected with reason `E-NOT-YET`. On or after
   `valid_to` it is rejected with `E-EXPIRED`.
4. [R-CPN-004] When `per_user_limit` is not None and the code's usage count is greater than or equal to it,
   the coupon is rejected with `E-LIMIT`.
5. [R-CPN-005] Coupons that share the same non-None `group` exclude each other: once one coupon of a group
   has been applied, every later coupon of that group is rejected with `E-GROUP`. A coupon that was rejected
   for any reason does not use up its group.
6. [R-CPN-006] A coupon's eligible amount is, for an unscoped coupon, `subtotal` minus the discounts all
   earlier applied coupons gave. For a scoped coupon it is the subtotal of the items whose `category` equals
   its `scope`, minus the discounts earlier applied coupons of that same scope gave. A discount from an
   unscoped coupon never reduces any scope's eligible amount.
7. [R-CPN-007] When the eligible amount is less than `min_spend_cents`, the coupon is rejected with
   `E-MIN-SPEND`. Equal is enough.
8. [R-CPN-008] The raw discount is: for `percent`, `eligible × value / 100` rounded half-up; for `fixed`,
   `value`; for `bogo`, take every unit of the eligible items (the items in scope, or all items for an
   unscoped coupon), each priced at its `unit_cents`, sort the units by price ascending, and the cheapest
   `n // 2` of the `n` units are free, so the discount is the sum of their prices.
9. [R-CPN-009] When `cap_cents` is not None the discount is at most `cap_cents`.
10. [R-CPN-010] Whatever the kind, a coupon's discount is also at most its eligible amount and at most what is
    left of the cart (`subtotal` minus all discounts given so far), so `total` is never below 0. A coupon
    whose final discount is 0 is rejected with `E-NO-EFFECT`. Rejection checks run in this order and the first
    one that fails is the reason: not-yet/expired, `E-LIMIT`, `E-GROUP`, `E-MIN-SPEND`, `E-NO-EFFECT`.
11. [R-CPN-011] `applied` lists the applied coupons in the order they were applied, with each one's final
    discount. `discount` is the sum of those discounts and `total` is `subtotal - discount`. A coupon whose
    `kind` is not one of the three raises `ValueError("E-KIND")`, checked for every coupon in the list before
    anything else is done.
