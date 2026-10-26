import unittest
import leave as L


def err(t, f, *a, **k):
    with t.assertRaises(ValueError) as c:
        f(*a, **k)
    return str(c.exception)


class T(unittest.TestCase):
    def test_ac1_rates(self):
        for m, r in ((0, 1.0), (11, 1.0), (12, 1.25), (59, 1.25), (60, 1.75), (120, 1.75)):
            self.assertEqual(L.monthly_rate(m), r, m)

    def test_ac2_first_month(self):
        for d, v in (("2026-06-01", 1.0), ("2026-06-16", 0.5), ("2026-06-30", 0.0), ("2026-06-24", 0.0),
                     ("2026-06-23", 0.25), ("2026-02-15", 0.5), ("2028-02-15", 0.5), ("2026-01-11", 0.5),
                     ("2026-01-08", 0.75), ("2026-06-09", 0.5)):
            self.assertEqual(L.first_month_accrual(d), v, d)

    def test_ac3_counts(self):
        self.assertEqual(L.working_days("2026-06-15", "2026-06-19"), 5.0)
        self.assertEqual(L.working_days("2026-06-15", "2026-06-22"), 6.0)
        self.assertEqual(L.working_days("2026-06-20", "2026-06-21"), 0.0)
        self.assertEqual(L.working_days("2026-06-15", "2026-06-15"), 1.0)

    def test_ac3_holidays(self):
        self.assertEqual(L.working_days("2026-06-15", "2026-06-19", {"2026-06-17"}), 4.0)
        self.assertEqual(L.working_days("2026-06-15", "2026-06-19", ["2026-06-20", "2026-06-17"]), 4.0)
        self.assertEqual(L.working_days("2026-06-15", "2026-06-19", {"2026-07-01"}), 5.0)
        self.assertEqual(L.working_days("2026-06-15", "2026-06-19", {"2026-06-15", "2026-06-19"}), 3.0)

    def test_ac4_halves(self):
        self.assertEqual(L.working_days("2026-06-15", "2026-06-17", start_half=True), 2.5)
        self.assertEqual(L.working_days("2026-06-15", "2026-06-17", end_half=True), 2.5)
        self.assertEqual(L.working_days("2026-06-15", "2026-06-17", start_half=True, end_half=True), 2.0)

    def test_ac4_single_day(self):
        self.assertEqual(L.working_days("2026-06-15", "2026-06-15", start_half=True), 0.5)
        self.assertEqual(L.working_days("2026-06-15", "2026-06-15", end_half=True), 0.5)
        self.assertEqual(err(self, L.working_days, "2026-06-15", "2026-06-15", (), True, True), "E-HALF")

    def test_ac4_half_on_non_working_day(self):
        self.assertEqual(L.working_days("2026-06-20", "2026-06-22", start_half=True), 1.0)
        self.assertEqual(L.working_days("2026-06-15", "2026-06-16", {"2026-06-15"}, start_half=True), 1.0)
        self.assertEqual(L.working_days("2026-06-18", "2026-06-20", end_half=True), 2.0)

    def test_ac5_carry_over(self):
        for b, res in ((3.0, (3.0, 0.0)), (5.0, (5.0, 0.0)), (7.5, (5.0, 2.5)), (0, (0.0, 0.0)), (-2.0, (-2.0, 0.0))):
            self.assertEqual(L.carry_over(b), res, b)

    def test_ac6_usable_carry(self):
        self.assertEqual(L.usable_carry(4.0, "2026-03-31", 2026), 4.0)
        self.assertEqual(L.usable_carry(4.0, "2026-04-01", 2026), 0.0)
        self.assertEqual(L.usable_carry(4.0, "2026-01-01", 2026), 4.0)
        self.assertEqual(L.usable_carry(4.0, "2027-02-01", 2026), 0.0)

    def test_ac7_carry_first(self):
        r = L.request(10.0, 3.0, "2026-03-30", "2026-04-02")
        self.assertEqual((r["status"], r["days"], r["from_carry"], r["from_balance"], r["balance_after"],
                          r["carry_after"]), ("approved", 4.0, 3.0, 1.0, 9.0, 0.0))

    def test_ac7_carry_covers_everything(self):
        r = L.request(10.0, 3.0, "2026-03-02", "2026-03-03")
        self.assertEqual((r["from_carry"], r["from_balance"], r["balance_after"], r["carry_after"]),
                         (2.0, 0.0, 10.0, 1.0))

    def test_ac7_expired_carry(self):
        r = L.request(10.0, 3.0, "2026-04-06", "2026-04-08")
        self.assertEqual((r["from_carry"], r["from_balance"], r["balance_after"], r["carry_after"]),
                         (0.0, 3.0, 7.0, 0.0))

    def test_ac8_overdraft_needs_approval(self):
        r = L.request(1.0, 0.0, "2026-06-15", "2026-06-17")
        self.assertEqual((r["status"], r["reason"], r["from_carry"], r["from_balance"], r["balance_after"],
                          r["carry_after"]), ("needs_approval", "E-APPROVAL", 0.0, 0.0, 1.0, 0.0))
        m = L.request(1.0, 0.0, "2026-06-15", "2026-06-17", manager_ok=True)
        self.assertEqual((m["status"], m["reason"], m["balance_after"]), ("approved", None, -2.0))

    def test_ac8_limits(self):
        z = L.request(3.0, 0.0, "2026-06-15", "2026-06-17")
        self.assertEqual((z["status"], z["balance_after"]), ("approved", 0.0))
        edge = L.request(0.0, 0.0, "2026-06-15", "2026-06-17", manager_ok=True)
        self.assertEqual((edge["status"], edge["balance_after"]), ("approved", -3.0))
        self.assertEqual(L.request(0.0, 0.0, "2026-06-15", "2026-06-17")["status"], "needs_approval")
        d = L.request(0.0, 0.0, "2026-06-15", "2026-06-18", end_half=True, manager_ok=True)
        self.assertEqual((d["status"], d["reason"], d["balance_after"], d["from_balance"]),
                         ("denied", "E-BALANCE", 0.0, 0.0))
        h = L.request(0.0, 0.0, "2026-06-15", "2026-06-15", start_half=True)
        self.assertEqual((h["status"], h["days"]), ("needs_approval", 0.5))

    def test_ac8_not_approved_keeps_carry(self):
        r = L.request(0.0, 2.0, "2026-04-06", "2026-04-12", manager_ok=False)
        self.assertEqual((r["status"], r["carry_after"], r["balance_after"]), ("denied", 2.0, 0.0))

    def test_ac9_no_workdays(self):
        for kw in ({}, {"manager_ok": True}):
            r = L.request(5.0, 1.0, "2026-06-20", "2026-06-21", **kw)
            self.assertEqual((r["status"], r["reason"], r["days"], r["balance_after"], r["carry_after"]),
                             ("denied", "E-NO-WORKDAYS", 0.0, 5.0, 1.0))
        h = L.request(5.0, 0.0, "2026-06-15", "2026-06-15", {"2026-06-15"})
        self.assertEqual((h["status"], h["reason"]), ("denied", "E-NO-WORKDAYS"))

    def test_ac10_cancel_refunds(self):
        req = L.request(10.0, 3.0, "2026-03-30", "2026-04-02")
        self.assertEqual(L.cancel(req, 9.0, 0.0, "2026-03-31"), {"balance": 10.0, "carry": 3.0})
        self.assertEqual(L.cancel(req, 9.0, 0.0, "2026-04-01"), {"balance": 13.0, "carry": 0.0})

    def test_ac10_cancel_balance_only(self):
        req = L.request(10.0, 0.0, "2026-06-15", "2026-06-17")
        self.assertEqual(L.cancel(req, 7.0, 0.0, "2026-06-10"), {"balance": 10.0, "carry": 0.0})

    def test_ac10_cancel_not_approved(self):
        req = L.request(0.0, 0.0, "2026-06-15", "2026-06-17")
        self.assertEqual(err(self, L.cancel, req, 0.0, 0.0, "2026-06-10"), "E-STATE")

    def test_ac11_dates(self):
        for bad in ("2026-02-30", "15/06/2026", "", None, "2026-6-1", "2026-13-01"):
            self.assertEqual(err(self, L.first_month_accrual, bad), "E-DATE", bad)
        self.assertEqual(err(self, L.working_days, "2026-06-15", "tomorrow"), "E-DATE")
        self.assertEqual(err(self, L.request, 1.0, 0.0, "bad", "2026-06-15"), "E-DATE")
        self.assertEqual(err(self, L.usable_carry, 1.0, "bad", 2026), "E-DATE")

    def test_ac11_tenure(self):
        for bad in (-1, 1.5, "12", None):
            self.assertEqual(err(self, L.monthly_rate, bad), "E-TENURE", bad)

    def test_ac11_range_and_order(self):
        self.assertEqual(err(self, L.working_days, "2026-06-20", "2026-06-15"), "E-RANGE")
        self.assertEqual(err(self, L.request, 1.0, 0.0, "2026-06-20", "2026-06-15"), "E-RANGE")
        self.assertEqual(err(self, L.working_days, "2026-06-20", "2026-06-15", (), True, True), "E-RANGE")
        self.assertEqual(err(self, L.working_days, "bad", "2026-06-15", (), True, True), "E-DATE")

    def test_ac11_result_keys(self):
        r = L.request(5.0, 0.0, "2026-06-15", "2026-06-15")
        self.assertEqual(sorted(r), ["balance_after", "carry_after", "days", "from_balance", "from_carry",
                                     "reason", "start", "status"])
        self.assertIsNone(r["reason"])
        self.assertEqual(r["start"], "2026-06-15")
