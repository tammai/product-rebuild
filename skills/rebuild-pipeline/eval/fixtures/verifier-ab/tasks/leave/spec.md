# Leave balances

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

## Acceptance criteria

1. [R-LV-001] `monthly_rate`: tenure of 0 to 11 months accrues 1.0 day a month, 12 to 59 months accrues
   1.25, and 60 months or more accrues 1.75.
2. [R-LV-002] `first_month_accrual(join_date)` is the tenure-0 monthly rate (1.0) times
   `days_remaining / days_in_month`, where `days_remaining` counts the join day through the last day of its
   month, rounded DOWN to a multiple of 0.25. Joining on the 1st gives 1.0.
3. [R-LV-003] `working_days(start, end, holidays)` counts the days from `start` to `end`, both inclusive,
   that fall on Monday to Friday and are not in `holidays`. A holiday on a weekend is not subtracted again.
4. [R-LV-004] With `start_half` true the first day counts 0.5 instead of 1, and with `end_half` true the
   last day counts 0.5. A half-day flag on a day that does not count (weekend or holiday) changes nothing.
   When `start == end`, one flag gives 0.5 on a working day, and both flags together are an error,
   `ValueError("E-HALF")`.
5. [R-LV-005] `carry_over(balance)` carries at most 5.0 days into the new year: a balance of 5.0 or less is
   carried whole, and the part above 5.0 is forfeited. A negative balance is carried whole (the debt carries
   over) and nothing is forfeited. It returns `(carried, forfeited)`.
6. [R-LV-006] Carried days from the previous year can be used through March 31 of `year`, inclusive.
   `usable_carry(carried, on_date, year)` returns `carried` when `on_date` is on or before that date, and
   0.0 after it.
7. [R-LV-007] `request` takes `days = working_days(...)`. Carry is spent first: the carry usable on the
   request's `start` date (`usable_carry(carry, start, start's year)`) covers as many of the days as it can
   (`from_carry`), and the rest comes from `balance` (`from_balance`). `balance_after` is `balance -
   from_balance`. `carry_after` is `carry - from_carry`, or 0.0 when `start` is after March 31 of its year
   (the carry has expired).
8. [R-LV-008] A request that leaves `balance_after` at 0 or more has `status` `"approved"`. One that
   leaves it below 0 but not below -3.0 has status `"needs_approval"` with reason `"E-APPROVAL"`, unless
   `manager_ok` is true, which makes it `"approved"`. One that would leave it below -3.0 has status
   `"denied"` with reason `"E-BALANCE"`, whatever `manager_ok` says. A request that is not approved changes
   nothing: `from_carry` and `from_balance` are 0.0 and `balance_after` and `carry_after` equal the balance
   and carry passed in.
9. [R-LV-009] A request for 0 days (no working days in the range) is `"denied"` with reason
   `"E-NO-WORKDAYS"`, with nothing changed, even when `manager_ok` is true.
10. [R-LV-010] `cancel(req, balance, carry, today)` takes an approved request's result and gives its days
    back. `from_balance` goes back to the balance. `from_carry` goes back to the carry if `today` is on or
    before March 31 of the year of `req["start"]`, and otherwise to the balance. Cancelling a request that
    is not approved raises `ValueError("E-STATE")`.
11. [R-LV-011] A date that is not a valid zero-padded ISO date string raises `ValueError("E-DATE")`.
    `monthly_rate` with a tenure that is negative or not an int raises `ValueError("E-TENURE")`. In
    `working_days` and `request`, `end` before `start` raises `ValueError("E-RANGE")`. Checks run in the
    order `E-DATE` (start, then end), `E-RANGE`, `E-HALF`. A result dict from `request` has the keys
    `status`, `reason` (None when approved), `days`, `from_carry`, `from_balance`, `balance_after`,
    `carry_after` and `start`.
