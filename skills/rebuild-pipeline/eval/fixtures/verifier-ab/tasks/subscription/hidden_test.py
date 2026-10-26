import unittest
from subscription import Subscription as S


def err(test, fn, *a):
    with test.assertRaises(ValueError) as c:
        fn(*a)
    return str(c.exception)


class T(unittest.TestCase):
    def test_ac1_trial_boundary(self):
        s = S(1000, 30, 0)
        self.assertEqual([s.status(d) for d in (0, 13, 14)], ["trial", "trial", "active"])

    def test_ac1_trial_offset_start(self):
        s = S(1000, 30, 100)
        self.assertEqual([s.status(d) for d in (100, 113, 114)], ["trial", "trial", "active"])

    def test_ac1_renewals_stay_active(self):
        s = S(1000, 30, 0)
        self.assertEqual([s.status(d) for d in (14, 43, 44, 200)], ["active"] * 4)

    def test_ac2_failed_then_grace(self):
        s = S(1000, 30, 0)
        s.payment_failed(20)
        self.assertEqual([s.status(d) for d in (20, 22, 23)], ["past_due", "past_due", "canceled"])

    def test_ac2_failed_outside_active(self):
        self.assertEqual(err(self, S(1000, 30, 0).payment_failed, 5), "E-TRANSITION")
        s = S(1000, 30, 0)
        s.payment_failed(20)
        self.assertEqual(err(self, s.payment_failed, 21), "E-TRANSITION")

    def test_ac3_recover_keeps_anchor(self):
        s = S(1000, 30, 0)
        s.payment_failed(20)
        s.payment_succeeded(21)
        self.assertEqual(s.status(21), "active")
        self.assertEqual(s.upgrade(2000, 50), 800)

    def test_ac3_succeeded_noop_when_active(self):
        s = S(1000, 30, 0)
        s.payment_succeeded(20)
        self.assertEqual(s.status(20), "active")

    def test_ac3_succeeded_in_trial_or_canceled(self):
        self.assertEqual(err(self, S(1000, 30, 0).payment_succeeded, 3), "E-TRANSITION")
        s = S(1000, 30, 0)
        s.payment_failed(20)
        self.assertEqual(err(self, s.payment_succeeded, 30), "E-TRANSITION")

    def test_ac4_cancel_in_trial(self):
        s = S(1000, 30, 0)
        s.cancel(5)
        self.assertEqual(s.status(5), "canceled")

    def test_ac4_cancel_active_ends_at_period_end(self):
        s = S(1000, 30, 0)
        self.assertFalse(s.cancel_at_period_end)
        s.cancel(20)
        self.assertTrue(s.cancel_at_period_end)
        self.assertEqual([s.status(d) for d in (20, 43, 44)], ["active", "active", "canceled"])

    def test_ac4_cancel_in_later_period(self):
        s = S(1000, 30, 0)
        s.cancel(50)
        self.assertEqual([s.status(d) for d in (73, 74)], ["active", "canceled"])

    def test_ac4_cancel_past_due_is_immediate(self):
        s = S(1000, 30, 0)
        s.payment_failed(20)
        s.cancel(21)
        self.assertEqual(s.status(21), "canceled")

    def test_ac4_cancel_when_canceled(self):
        s = S(1000, 30, 0)
        s.cancel(5)
        self.assertEqual(err(self, s.cancel, 6), "E-TRANSITION")

    def test_ac5_first_day_full_difference(self):
        s = S(1000, 30, 0)
        self.assertEqual(s.upgrade(1900, 14), 900)
        self.assertEqual(s.plan_cents, 1900)

    def test_ac5_floor_not_round(self):
        s = S(1000, 30, 0)
        self.assertEqual(s.upgrade(2015, 43), 33)

    def test_ac5_mid_period_and_chained(self):
        s = S(1000, 30, 0)
        self.assertEqual(s.upgrade(2001, 20), 800)
        self.assertEqual(s.upgrade(3001, 20), 800)

    def test_ac5_errors_and_order(self):
        s = S(1000, 30, 0)
        self.assertEqual(err(self, s.upgrade, 1000, 20), "E-UPGRADE")
        self.assertEqual(err(self, s.upgrade, 900, 20), "E-UPGRADE")
        self.assertEqual(err(self, S(1000, 30, 0).upgrade, 900, 5), "E-TRANSITION")
        p = S(1000, 30, 0)
        p.payment_failed(20)
        self.assertEqual(err(self, p.upgrade, 2000, 21), "E-TRANSITION")

    def test_ac6_canceled_is_final(self):
        for make in (lambda: self._cancel_trial(), lambda: self._grace_cancel()):
            s = make()
            self.assertEqual(err(self, s.payment_failed, 40), "E-TRANSITION")
            self.assertEqual(err(self, s.payment_succeeded, 40), "E-TRANSITION")
            self.assertEqual(err(self, s.cancel, 40), "E-TRANSITION")
            self.assertEqual(err(self, s.upgrade, 5000, 40), "E-TRANSITION")
            self.assertEqual(s.status(40), "canceled")

    def _cancel_trial(self):
        s = S(1000, 30, 0)
        s.cancel(2)
        return s

    def _grace_cancel(self):
        s = S(1000, 30, 0)
        s.payment_failed(20)
        s.status(30)
        return s
