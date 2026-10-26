import unittest
from shipping import quote as Q


def P(w=1.0, l=10, wd=10, h=10, hz=False):
    return {"weight_kg": w, "l_cm": l, "w_cm": wd, "h_cm": h, "hazmat": hz}


def err(t, *a, **k):
    with t.assertRaises(ValueError) as c:
        Q(*a, **k)
    return str(c.exception)


class T(unittest.TestCase):
    def test_ac1_rounds_up_to_half(self):
        for w, b in ((1.2, 1.5), (1.5, 1.5), (1.0, 1.0), (0.1, 0.5), (2.01, 2.5)):
            self.assertEqual(Q([P(w)], "Z1")["billable_kg"], [b], w)

    def test_ac1_dimensional_weight(self):
        self.assertEqual(Q([P(2.0, 40, 30, 25)], "Z1")["billable_kg"], [6.0])
        self.assertEqual(Q([P(2.0, 40, 30, 26)], "Z1")["billable_kg"], [6.5])
        self.assertEqual(Q([P(6.3, 40, 30, 25)], "Z1")["billable_kg"], [6.5])

    def test_ac1_list_in_input_order(self):
        self.assertEqual(Q([P(1.2), P(0.1), P(2.2)], "Z1")["billable_kg"], [1.5, 0.5, 2.5])

    def test_ac2_bands(self):
        for w, base in ((1.0, 510), (1.2, 810), (2.0, 810), (2.1, 1410), (5.0, 1410), (5.1, 2510),
                        (10.0, 2510), (10.1, 4510), (30.0, 4510)):
            self.assertEqual(Q([P(w)], "Z1")["base"], base, w)

    def test_ac2_base_is_sum(self):
        self.assertEqual(Q([P(1.0), P(5.1)], "Z1")["base"], 3020)

    def test_ac3_express_half_up(self):
        for w, base in ((1.0, 842), (1.2, 1337), (2.1, 2327), (5.1, 4142), (10.1, 7442)):
            self.assertEqual(Q([P(w)], "Z1", "express")["base"], base, w)

    def test_ac3_express_rounds_per_parcel(self):
        self.assertEqual(Q([P(1.0), P(1.0)], "Z1", "express")["base"], 1684)

    def test_ac3_standard_unchanged(self):
        self.assertEqual(Q([P(1.0)], "Z1", "standard")["base"], 510)

    def test_ac4_discount_three_parcels(self):
        r = Q([P(1.0)] * 3, "Z1")
        self.assertEqual((r["base"], r["discount"]), (1530, 77))

    def test_ac4_no_discount_under_three(self):
        self.assertEqual(Q([P(1.0)] * 2, "Z1")["discount"], 0)

    def test_ac4_discount_on_express_base(self):
        r = Q([P(1.0)] * 3, "Z1", "express")
        self.assertEqual((r["base"], r["discount"]), (2526, 126))

    def test_ac4_discount_ignores_zone_fee(self):
        self.assertEqual(Q([P(1.0)] * 3, "Z2")["discount"], 77)

    def test_ac5_zone_fees(self):
        for z, f in (("Z1", 0), ("Z2", 300), ("Z3", 750), ("Z4", 1500)):
            self.assertEqual(Q([P(1.0)], z)["zone_fee"], f, z)

    def test_ac5_per_parcel(self):
        self.assertEqual(Q([P(1.0), P(1.0)], "Z2")["zone_fee"], 600)

    def test_ac6_fuel_rounds_to_nearest(self):
        self.assertEqual(Q([P(1.0)], "Z1")["fuel"], 43)
        self.assertEqual(Q([P(1.0)], "Z2")["fuel"], 69)

    def test_ac6_fuel_base_excludes_z4_zone_fee(self):
        self.assertEqual(Q([P(1.0)], "Z4")["fuel"], 43)

    def test_ac6_fuel_after_discount(self):
        self.assertEqual(Q([P(1.0)] * 3, "Z2")["fuel"], 200)

    def test_ac6_fuel_excludes_hazmat_and_insurance(self):
        self.assertEqual(Q([P(1.0, hz=True)], "Z1", declared_cents=100000)["fuel"], 43)

    def test_ac7_insurance(self):
        for d, i in ((0, 0), (1, 150), (5000, 150), (20050, 201), (100000, 1000), (600000, 5000), (500000, 5000)):
            self.assertEqual(Q([P(1.0)], "Z1", declared_cents=d)["insurance"], i, d)

    def test_ac8_hazmat_fee(self):
        self.assertEqual(Q([P(1.0, hz=True)], "Z1")["hazmat"], 1200)
        self.assertEqual(Q([P(1.0, hz=True), P(1.0), P(1.0, hz=True)], "Z1")["hazmat"], 2400)
        self.assertEqual(Q([P(1.0)], "Z1")["hazmat"], 0)

    def test_ac8_hazmat_missing_key_ok(self):
        p = P(1.0)
        del p["hazmat"]
        self.assertEqual(Q([p], "Z1")["hazmat"], 0)

    def test_ac9_simple_errors(self):
        self.assertEqual(err(self, [], "Z1"), "E-EMPTY")
        for s in ("overnight", "Express", ""):
            self.assertEqual(err(self, [P()], "Z1", s), "E-SERVICE")
        for z in ("Z5", "z1", ""):
            self.assertEqual(err(self, [P()], z), "E-ZONE")
        for d in (-1, 1.5, "100", None):
            self.assertEqual(err(self, [P()], "Z1", "standard", d), "E-DECLARED")

    def test_ac9_parcel_errors(self):
        for bad in (P(0), P(-1), P(1.0, 0), P(1.0, 10, 1.5), P(1.0, 10, 10, "10"), P("1")):
            self.assertEqual(err(self, [bad], "Z1"), "E-PARCEL")
        self.assertEqual(err(self, [P(30.1)], "Z1"), "E-WEIGHT")
        self.assertEqual(err(self, [P(1.0, 100, 100, 100)], "Z1"), "E-WEIGHT")
        self.assertEqual(err(self, [P(1.0, hz=True)], "Z1", "express"), "E-HAZMAT")

    def test_ac9_check_order(self):
        self.assertEqual(err(self, [], "Z9", "bad"), "E-EMPTY")
        self.assertEqual(err(self, [P()], "Z9", "bad"), "E-SERVICE")
        self.assertEqual(err(self, [P()], "Z9", "standard", -5), "E-ZONE")
        self.assertEqual(err(self, [P(0)], "Z1", "standard", -5), "E-DECLARED")

    def test_ac9_parcel_by_parcel(self):
        self.assertEqual(err(self, [P(0), P(31)], "Z1"), "E-PARCEL")
        self.assertEqual(err(self, [P(31), P(0)], "Z1"), "E-WEIGHT")
        self.assertEqual(err(self, [P(1.0, hz=True), P(0)], "Z1", "express"), "E-HAZMAT")
        self.assertEqual(err(self, [P(31, hz=True)], "Z1", "express"), "E-HAZMAT")
        self.assertEqual(err(self, [P(0, hz=True)], "Z1", "express"), "E-PARCEL")

    def test_ac10_waiver_at_threshold(self):
        r = Q([P(10.1), P(1.0)], "Z2")
        self.assertEqual((r["base"], r["zone_fee"]), (5020, 0))
        self.assertEqual(Q([P(5.1), P(5.1)], "Z3")["zone_fee"], 0)

    def test_ac10_below_threshold_pays(self):
        self.assertEqual(Q([P(5.1), P(2.1)], "Z2")["zone_fee"], 600)

    def test_ac10_z4_never_waived(self):
        self.assertEqual(Q([P(10.1), P(10.1)], "Z4")["zone_fee"], 3000)

    def test_ac10_waived_fee_not_in_fuel(self):
        self.assertEqual(Q([P(10.1), P(1.0)], "Z2")["fuel"], 427)

    def test_ac10_threshold_uses_discounted_base(self):
        r = Q([P(10.1)] * 3, "Z2")
        self.assertEqual((r["base"], r["discount"], r["zone_fee"]), (13530, 677, 0))

    def test_ac11_total(self):
        r = Q([P(10.1), P(1.0, hz=True), P(1.2)], "Z3", declared_cents=20050)
        self.assertEqual((r["base"], r["discount"], r["zone_fee"], r["hazmat"], r["fuel"], r["insurance"], r["total"]),
                         (5830, 292, 0, 1200, 471, 201, 7410))

    def test_ac11_total_with_fees(self):
        r = Q([P(1.0)], "Z4", declared_cents=1000)
        self.assertEqual(r["total"], 510 - 0 + 1500 + 0 + 43 + 150)
