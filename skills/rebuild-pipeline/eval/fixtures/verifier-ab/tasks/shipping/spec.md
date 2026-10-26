# Parcel shipping quote

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

## Acceptance criteria

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
