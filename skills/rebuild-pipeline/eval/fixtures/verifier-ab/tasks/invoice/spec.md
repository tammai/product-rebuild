# Invoice totals

Module `invoice`, file `invoice.py`, Python 3.9+, standard library only.

```python
compute_invoice(lines, discount_code=None, region="US") -> dict
```

`lines` is a list of dicts `{"sku": str, "qty": int, "unit_cents": int}`. The result is
`{"subtotal": int, "discount": int, "tax": int, "total": int}`, every value in whole cents.
Rounding "half-up" means a value exactly halfway between two cents rounds up.

## Acceptance criteria

1. [R-INV-001] A line's amount is `qty × unit_cents`. `subtotal` is the sum of the line amounts.
2. [R-INV-002] Discount code `"SAVE10"` takes 10% off each line's amount, rounded half-up to the
   cent, but only when `subtotal` is at least 5000 cents. Any other code, including `None` and
   `"save10"`, gives no discount. `discount` is the sum of the per-line discounts.
3. [R-INV-003] Tax is computed per line, on that line's amount after its discount, at the region's
   rate, rounded half-up to the cent. `tax` is the sum of the per-line taxes. Rates: `US` 7%,
   `EU` 20%, `JP` 10%.
4. [R-INV-004] `total` is `subtotal - discount + tax`.
5. [R-INV-005] An unknown region (region names are case-sensitive) raises `ValueError` whose
   message is exactly `E-REGION`.
6. [R-INV-006] An empty `lines` list raises `ValueError("E-EMPTY")`. A line whose `qty` is not a
   positive integer raises `ValueError("E-QTY")`. Validation order: `E-EMPTY`, then `E-QTY`
   (lines in order), then `E-REGION`.
