# Subscription lifecycle and upgrade proration

Module `subscription`, file `subscription.py`, Python 3.9+, standard library only. Time is whole
days, passed in by the caller as an integer `day` that does not go backwards. Nothing reads a clock.

```python
Subscription(plan_cents, period_days, start_day)
.status(day) -> "trial" | "active" | "past_due" | "canceled"
.payment_failed(day)      .payment_succeeded(day)      .cancel(day)
.upgrade(new_plan_cents, day) -> int      # the prorated charge, in whole cents
.cancel_at_period_end -> bool             # True once cancel() was called on an active subscription
.plan_cents -> int                        # the current plan price
```

The trial is 14 days: days `start_day` to `start_day + 13`. From `start_day + 14` the subscription is
active, and its first paid period starts that day. Paid periods are `period_days` long and renew
back to back from there: a period starting on day `p` covers days `p` to `p + period_days - 1`.
Every method first brings the subscription up to date for the `day` it is given.

## Acceptance criteria

1. [R-SUB-001] A new subscription is `trial` on days `start_day` to `start_day + 13`, and `active`
   from `start_day + 14`, and it stays `active` across period renewals while nothing else happens.
2. [R-SUB-002] `payment_failed(day)` on an `active` subscription makes it `past_due`. It stays
   `past_due` for 3 days: with the failure on day `f`, it is `past_due` through day `f + 2` and
   `canceled` from day `f + 3`. `payment_failed` in any other status raises `ValueError("E-TRANSITION")`.
3. [R-SUB-003] `payment_succeeded(day)` on a `past_due` subscription makes it `active` again and
   does not move the billing periods (they stay anchored at `start_day + 14`). On an `active`
   subscription it does nothing. In `trial` or `canceled` it raises `ValueError("E-TRANSITION")`.
4. [R-SUB-004] `cancel(day)`: in `trial` or `past_due` the status becomes `canceled` immediately. On
   an `active` subscription the status stays `active`, `cancel_at_period_end` becomes True, and the
   status becomes `canceled` on the first day of the next period (the day the current period ends).
   In `canceled` it raises `ValueError("E-TRANSITION")`.
5. [R-SUB-005] `upgrade(new_plan_cents, day)` on an `active` subscription returns the charge
   `(new_plan_cents - plan_cents) × remaining_days // period_days` (integer floor division), where
   `remaining_days` is the current period's end day minus `day`; on a period's first day it is
   `period_days`. It then sets `plan_cents` to the new price. If `new_plan_cents` is not greater than
   the current price it raises `ValueError("E-UPGRADE")`. In any other status it raises
   `ValueError("E-TRANSITION")`, and that check comes first.
6. [R-SUB-006] `canceled` is final: every one of `payment_failed`, `payment_succeeded`, `cancel` and
   `upgrade` on a `canceled` subscription, however it got there, raises `ValueError("E-TRANSITION")`
   and leaves the status `canceled`.
