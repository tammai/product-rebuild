import unittest
from ratelimit import RateLimiter as RL


class T(unittest.TestCase):
    def test_ac1_limit(self):
        r = RL(3, 10)
        self.assertEqual([r.check("k", t)[0] for t in (0, 1, 2, 3)], [True, True, True, False])

    def test_ac1_expiry_is_exact(self):
        r = RL(1, 10)
        self.assertTrue(r.check("k", 0)[0])
        self.assertFalse(r.check("k", 9.999)[0])
        self.assertTrue(r.check("k", 10)[0])

    def test_ac1_sliding_not_fixed(self):
        r = RL(2, 10)
        self.assertTrue(r.check("k", 0)[0])
        self.assertTrue(r.check("k", 9)[0])
        self.assertTrue(r.check("k", 10)[0])
        self.assertFalse(r.check("k", 11)[0])

    def test_ac2_retry_after_rounds_up(self):
        r = RL(1, 10)
        r.check("k", 0)
        self.assertEqual(r.check("k", 3.5), (False, 7))
        self.assertEqual(r.check("k", 4), (False, 6))
        self.assertEqual(r.check("k", 9.9), (False, 1))

    def test_ac2_retry_after_minimum_one(self):
        r = RL(1, 10)
        r.check("k", 0)
        self.assertEqual(r.check("k", 9.9999)[1], 1)

    def test_ac2_retry_after_uses_oldest(self):
        r = RL(2, 10)
        r.check("k", 0)
        r.check("k", 6)
        self.assertEqual(r.check("k", 7), (False, 3))

    def test_ac3_allowed_shape(self):
        self.assertEqual(RL(1, 5).check("k", 0), (True, 0))

    def test_ac4_denied_not_counted(self):
        r = RL(1, 10)
        self.assertTrue(r.check("k", 0)[0])
        self.assertFalse(r.check("k", 5)[0])
        self.assertTrue(r.check("k", 10)[0])

    def test_ac4_denied_does_not_move_window(self):
        r = RL(2, 10)
        r.check("k", 0)
        r.check("k", 1)
        r.check("k", 2)
        r.check("k", 3)
        self.assertTrue(r.check("k", 10)[0])
        self.assertEqual(r.check("k", 10.5), (False, 1))

    def test_ac5_keys_independent(self):
        r = RL(1, 10)
        self.assertTrue(r.check("a", 0)[0])
        self.assertTrue(r.check("b", 0)[0])
        self.assertFalse(r.check("a", 1)[0])

    def test_ac5_reset(self):
        r = RL(1, 10)
        r.check("a", 0)
        r.check("b", 0)
        r.reset("a")
        self.assertTrue(r.check("a", 1)[0])
        self.assertFalse(r.check("b", 1)[0])

    def test_ac5_reset_unknown(self):
        RL(1, 10).reset("never")

    def test_ac6_bad_config(self):
        for a in ((0, 10), (-1, 10), (1.5, 10), (2, 0), (2, -5), ("2", 10), (2, "10")):
            with self.assertRaises(ValueError) as c:
                RL(*a)
            self.assertEqual(str(c.exception), "E-CONFIG")

    def test_ac6_float_window_ok(self):
        RL(1, 0.5)
