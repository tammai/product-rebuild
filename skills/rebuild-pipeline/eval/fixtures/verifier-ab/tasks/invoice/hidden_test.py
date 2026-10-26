import unittest
from invoice import compute_invoice as ci


def L(q, u):
    return {"sku": "x", "qty": q, "unit_cents": u}


class T(unittest.TestCase):
    def test_ac1_subtotal(self):
        self.assertEqual(ci([L(3, 100), L(1, 250)])["subtotal"], 550)

    def test_ac1_result_keys_are_ints(self):
        r = ci([L(2, 10)])
        self.assertEqual(sorted(r), ["discount", "subtotal", "tax", "total"])
        self.assertTrue(all(type(v) is int for v in r.values()))

    def test_ac2_threshold_inclusive_and_half_up(self):
        r = ci([L(1, 5), L(1, 4995)], "SAVE10")
        self.assertEqual((r["subtotal"], r["discount"]), (5000, 501))

    def test_ac2_below_threshold(self):
        self.assertEqual(ci([L(1, 5), L(1, 4994)], "SAVE10")["discount"], 0)

    def test_ac2_other_codes(self):
        for code in (None, "SAVE20", "save10", ""):
            self.assertEqual(ci([L(1, 6000)], code)["discount"], 0)

    def test_ac3_tax_half_up(self):
        self.assertEqual(ci([L(1, 25)], None, "JP")["tax"], 3)

    def test_ac3_tax_is_per_line(self):
        self.assertEqual(ci([L(1, 5), L(1, 5)], None, "JP")["tax"], 2)

    def test_ac3_tax_after_discount(self):
        r = ci([L(1, 5), L(1, 4995)], "SAVE10", "EU")
        self.assertEqual((r["discount"], r["tax"]), (501, 900))

    def test_ac3_rates(self):
        self.assertEqual(ci([L(1, 10000)], None, "US")["tax"], 700)
        self.assertEqual(ci([L(1, 10000)], None, "EU")["tax"], 2000)
        self.assertEqual(ci([L(1, 10000)], None, "JP")["tax"], 1000)

    def test_ac4_total(self):
        r = ci([L(1, 5), L(1, 4995)], "SAVE10", "EU")
        self.assertEqual(r["total"], 5000 - 501 + 900)

    def test_ac4_total_no_discount(self):
        r = ci([L(2, 333)], None, "US")
        self.assertEqual(r["total"], r["subtotal"] - r["discount"] + r["tax"])

    def test_ac5_unknown_region(self):
        for reg in ("XX", "us", ""):
            with self.assertRaises(ValueError) as c:
                ci([L(1, 10)], None, reg)
            self.assertEqual(str(c.exception), "E-REGION")

    def test_ac6_empty(self):
        with self.assertRaises(ValueError) as c:
            ci([])
        self.assertEqual(str(c.exception), "E-EMPTY")

    def test_ac6_bad_qty(self):
        for q in (0, -1, 1.5, "2"):
            with self.assertRaises(ValueError) as c:
                ci([L(q, 10)])
            self.assertEqual(str(c.exception), "E-QTY")

    def test_ac6_validation_order(self):
        with self.assertRaises(ValueError) as c:
            ci([], None, "XX")
        self.assertEqual(str(c.exception), "E-EMPTY")
        with self.assertRaises(ValueError) as c:
            ci([L(0, 1)], None, "XX")
        self.assertEqual(str(c.exception), "E-QTY")
