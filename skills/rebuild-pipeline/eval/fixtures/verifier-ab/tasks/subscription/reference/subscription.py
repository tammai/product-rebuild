class Subscription:
    TRIAL_DAYS = 14
    GRACE_DAYS = 3

    def __init__(self, plan_cents, period_days, start_day):
        self.plan_cents, self.period_days, self.start_day = plan_cents, period_days, start_day
        self._paid = start_day + self.TRIAL_DAYS
        self._state = "trial"
        self._failed = None
        self._cancel_at = None
        self.cancel_at_period_end = False

    def _period_end(self, day):
        k = (day - self._paid) // self.period_days
        return self._paid + (k + 1) * self.period_days

    def _sync(self, day):
        if self._state == "trial" and day >= self._paid:
            self._state = "active"
        if self._state == "past_due" and day - self._failed >= self.GRACE_DAYS:
            self._state = "canceled"
        if self._state == "active" and self._cancel_at is not None and day >= self._cancel_at:
            self._state = "canceled"

    def status(self, day):
        self._sync(day)
        return self._state

    def payment_failed(self, day):
        self._sync(day)
        if self._state != "active":
            raise ValueError("E-TRANSITION")
        self._state, self._failed = "past_due", day

    def payment_succeeded(self, day):
        self._sync(day)
        if self._state == "past_due":
            self._state = "active"
        elif self._state != "active":
            raise ValueError("E-TRANSITION")

    def cancel(self, day):
        self._sync(day)
        if self._state in ("trial", "past_due"):
            self._state = "canceled"
        elif self._state == "active":
            self.cancel_at_period_end = True
            self._cancel_at = self._period_end(day)
        else:
            raise ValueError("E-TRANSITION")

    def upgrade(self, new_plan_cents, day):
        self._sync(day)
        if self._state != "active":
            raise ValueError("E-TRANSITION")
        if new_plan_cents <= self.plan_cents:
            raise ValueError("E-UPGRADE")
        charge = (new_plan_cents - self.plan_cents) * (self._period_end(day) - day) // self.period_days
        self.plan_cents = new_plan_cents
        return charge
