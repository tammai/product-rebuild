import unittest
from coupons import price_cart as PC

TODAY = "2026-06-15"


def it(cat, unit, qty=1, sku="s"):
    return {"sku": sku, "category": cat, "unit_cents": unit, "qty": qty}


def cp(code, kind="fixed", value=0, **kw):
    d = {"code": code, "kind": kind, "value": value, "priority": 10, "scope": None, "min_spend_cents": 0,
         "valid_from": "2026-01-01", "valid_to": "2027-01-01", "group": None, "cap_cents": None,
         "per_user_limit": None}
    d.update(kw)
    return d


def codes(r):
    return [a["code"] for a in r["applied"]]


class T(unittest.TestCase):
    def test_ac1_subtotal_and_empty(self):
        r = PC([it("x", 1000, 2), it("y", 500, 3)], [], TODAY)
        self.assertEqual((r["subtotal"], r["total"], r["applied"], r["rejected"], r["discount"]),
                         (3500, 3500, [], {}, 0))

    def test_ac2_priority_order(self):
        items = [it("x", 10000)]
        a = PC(items, [cp("P", "percent", 10, priority=1), cp("F", "fixed", 500, priority=2)], TODAY)
        self.assertEqual((codes(a), a["total"]), (["P", "F"], 8500))
        b = PC(items, [cp("P", "percent", 10, priority=2), cp("F", "fixed", 500, priority=1)], TODAY)
        self.assertEqual((codes(b), b["total"]), (["F", "P"], 8550))

    def test_ac2_ties_by_code(self):
        r = PC([it("x", 10000)], [cp("B", "fixed", 500), cp("A", "percent", 10)], TODAY)
        self.assertEqual((codes(r), r["total"]), (["A", "B"], 8500))

    def test_ac2_priority_is_numeric(self):
        r = PC([it("x", 10000)], [cp("A", "fixed", 100, priority=10), cp("B", "fixed", 200, priority=9)], TODAY)
        self.assertEqual(codes(r), ["B", "A"])

    def test_ac3_validity_window(self):
        items = [it("x", 1000)]
        self.assertEqual(codes(PC(items, [cp("A", "fixed", 100, valid_from=TODAY)], TODAY)), ["A"])
        self.assertEqual(PC(items, [cp("A", "fixed", 100, valid_to=TODAY)], TODAY)["rejected"], {"A": "E-EXPIRED"})
        self.assertEqual(codes(PC(items, [cp("A", "fixed", 100, valid_to="2026-06-16")], TODAY)), ["A"])
        self.assertEqual(PC(items, [cp("A", "fixed", 100, valid_from="2026-06-16")], TODAY)["rejected"],
                         {"A": "E-NOT-YET"})
        self.assertEqual(PC(items, [cp("A", "fixed", 100, valid_to="2026-06-01")], TODAY)["rejected"],
                         {"A": "E-EXPIRED"})

    def test_ac4_per_user_limit(self):
        items = [it("x", 1000)]
        self.assertEqual(PC(items, [cp("X", "fixed", 100, per_user_limit=2)], TODAY, {"X": 2})["rejected"],
                         {"X": "E-LIMIT"})
        self.assertEqual(codes(PC(items, [cp("X", "fixed", 100, per_user_limit=2)], TODAY, {"X": 1})), ["X"])
        self.assertEqual(codes(PC(items, [cp("X", "fixed", 100)], TODAY, {"X": 99})), ["X"])
        self.assertEqual(codes(PC(items, [cp("X", "fixed", 100, per_user_limit=1)], TODAY, None)), ["X"])
        self.assertEqual(PC(items, [cp("X", "fixed", 100, per_user_limit=0)], TODAY)["rejected"], {"X": "E-LIMIT"})

    def test_ac5_group_exclusion(self):
        items = [it("x", 1000)]
        r = PC(items, [cp("G1", "fixed", 100, priority=1, group="g"), cp("G2", "fixed", 200, priority=2, group="g")],
               TODAY)
        self.assertEqual((codes(r), r["rejected"], r["total"]), (["G1"], {"G2": "E-GROUP"}, 900))

    def test_ac5_rejected_does_not_use_group(self):
        items = [it("x", 1000)]
        r = PC(items, [cp("G1", "fixed", 100, priority=1, group="g", valid_to="2026-01-02"),
                       cp("G2", "fixed", 200, priority=2, group="g")], TODAY)
        self.assertEqual((codes(r), r["rejected"]), (["G2"], {"G1": "E-EXPIRED"}))

    def test_ac5_no_group_never_excludes(self):
        r = PC([it("x", 1000)], [cp("A", "fixed", 100, priority=1), cp("B", "fixed", 100, priority=2)], TODAY)
        self.assertEqual(codes(r), ["A", "B"])

    def test_ac5_different_groups_coexist(self):
        r = PC([it("x", 1000)], [cp("A", "fixed", 100, priority=1, group="g"),
                                 cp("B", "fixed", 100, priority=2, group="h")], TODAY)
        self.assertEqual(codes(r), ["A", "B"])

    def test_ac6_unscoped_not_charged_to_scope(self):
        items = [it("x", 4000), it("y", 6000)]
        r = PC(items, [cp("U", "percent", 10, priority=1), cp("S", "percent", 50, priority=2, scope="x")], TODAY)
        self.assertEqual(([a["discount"] for a in r["applied"]], r["total"]), ([1000, 2000], 7000))

    def test_ac6_scoped_reduces_same_scope(self):
        items = [it("x", 4000), it("y", 6000)]
        r = PC(items, [cp("S1", "fixed", 1000, priority=1, scope="x"),
                       cp("S2", "percent", 50, priority=2, scope="x")], TODAY)
        self.assertEqual(([a["discount"] for a in r["applied"]], r["total"]), ([1000, 1500], 7500))

    def test_ac6_scoped_reduces_unscoped_eligible(self):
        items = [it("x", 4000), it("y", 6000)]
        r = PC(items, [cp("S", "percent", 50, priority=1, scope="x"), cp("U", "percent", 10, priority=2)], TODAY)
        self.assertEqual(([a["discount"] for a in r["applied"]], r["total"]), ([2000, 800], 7200))

    def test_ac6_scoped_other_scope_unaffected(self):
        items = [it("x", 4000), it("y", 6000)]
        r = PC(items, [cp("A", "percent", 50, priority=1, scope="x"), cp("B", "percent", 50, priority=2, scope="y")],
               TODAY)
        self.assertEqual([a["discount"] for a in r["applied"]], [2000, 3000])

    def test_ac7_min_spend_inclusive(self):
        items = [it("x", 4000), it("y", 6000)]
        self.assertEqual(codes(PC(items, [cp("A", "fixed", 100, scope="x", min_spend_cents=4000)], TODAY)), ["A"])
        self.assertEqual(PC(items, [cp("A", "fixed", 100, scope="x", min_spend_cents=4001)], TODAY)["rejected"],
                         {"A": "E-MIN-SPEND"})

    def test_ac7_min_spend_after_earlier_discounts(self):
        items = [it("x", 10000)]
        ok = PC(items, [cp("F", "fixed", 5000, priority=1), cp("P", "percent", 10, priority=2, min_spend_cents=5000)],
                TODAY)
        self.assertEqual(codes(ok), ["F", "P"])
        no = PC(items, [cp("F", "fixed", 5000, priority=1), cp("P", "percent", 10, priority=2, min_spend_cents=5001)],
                TODAY)
        self.assertEqual((codes(no), no["rejected"]), (["F"], {"P": "E-MIN-SPEND"}))

    def test_ac8_percent_half_up(self):
        r = PC([it("x", 1005)], [cp("A", "percent", 10)], TODAY)
        self.assertEqual(r["applied"], [{"code": "A", "discount": 101}])

    def test_ac8_fixed(self):
        r = PC([it("x", 3000)], [cp("A", "fixed", 5000)], TODAY)
        self.assertEqual((r["applied"], r["total"]), ([{"code": "A", "discount": 3000}], 0))

    def test_ac8_bogo_cheapest_free(self):
        items = [it("x", 300, 3), it("x", 500, 1)]
        self.assertEqual(PC(items, [cp("B", "bogo", scope="x")], TODAY)["discount"], 600)
        self.assertEqual(PC([it("x", 300, 2), it("x", 500, 1)], [cp("B", "bogo", scope="x")], TODAY)["discount"], 300)

    def test_ac8_bogo_across_lines_and_unscoped(self):
        items = [it("x", 700, 1), it("y", 200, 1), it("y", 400, 2)]
        self.assertEqual(PC(items, [cp("B", "bogo")], TODAY)["discount"], 200 + 400)
        self.assertEqual(PC(items, [cp("B", "bogo", scope="y")], TODAY)["discount"], 200)

    def test_ac8_bogo_pairs_floor(self):
        self.assertEqual(PC([it("x", 100, 5)], [cp("B", "bogo")], TODAY)["discount"], 200)

    def test_ac9_cap(self):
        self.assertEqual(PC([it("x", 10000)], [cp("A", "percent", 50, cap_cents=1000)], TODAY)["discount"], 1000)
        self.assertEqual(PC([it("x", 10000)], [cp("A", "fixed", 2000, cap_cents=500)], TODAY)["discount"], 500)
        self.assertEqual(PC([it("x", 10000)], [cp("A", "percent", 10, cap_cents=5000)], TODAY)["discount"], 1000)
        self.assertEqual(PC([it("x", 300, 4)], [cp("A", "bogo", cap_cents=100)], TODAY)["discount"], 100)

    def test_ac10_no_effect(self):
        r = PC([it("x", 1000)], [cp("A", "fixed", 100, scope="nope")], TODAY)
        self.assertEqual(r["applied"], [])
        self.assertEqual(r["rejected"], {"A": "E-NO-EFFECT"})
        self.assertEqual(PC([it("x", 1000)], [cp("B", "bogo")], TODAY)["rejected"], {"B": "E-NO-EFFECT"})
        self.assertEqual(PC([it("x", 1000)], [cp("Z", "percent", 0)], TODAY)["rejected"], {"Z": "E-NO-EFFECT"})

    def test_ac10_no_effect_does_not_use_group(self):
        r = PC([it("x", 1000)], [cp("A", "fixed", 100, priority=1, scope="nope", group="g"),
                                 cp("B", "fixed", 100, priority=2, group="g")], TODAY)
        self.assertEqual((codes(r), r["rejected"]), (["B"], {"A": "E-NO-EFFECT"}))

    def test_ac10_discount_never_exceeds_what_is_left(self):
        r = PC([it("x", 1000)], [cp("F", "fixed", 800, priority=1), cp("P", "percent", 100, priority=2),
                                 cp("G", "fixed", 100, priority=3)], TODAY)
        self.assertEqual(([a["discount"] for a in r["applied"]], r["total"], r["rejected"]),
                         ([800, 200], 0, {"G": "E-NO-EFFECT"}))

    def test_ac10_bogo_capped_by_remaining_and_eligible(self):
        r = PC([it("x", 500, 2)], [cp("U", "fixed", 900, priority=1), cp("B", "bogo", scope="x", priority=2)], TODAY)
        self.assertEqual(([a["discount"] for a in r["applied"]], r["total"]), ([900, 100], 0))
        r2 = PC([it("x", 500, 2)], [cp("S", "fixed", 800, priority=1, scope="x"), cp("B", "bogo", scope="x", priority=2)],
                TODAY)
        self.assertEqual(([a["discount"] for a in r2["applied"]], r2["total"]), ([800, 200], 0))

    def test_ac10_rejection_precedence(self):
        items = [it("x", 1000)]
        r = PC(items, [cp("G", "fixed", 100, priority=1, group="g"),
                       cp("L", "fixed", 100, priority=2, group="g", per_user_limit=1),
                       cp("M", "fixed", 100, priority=3, group="g", min_spend_cents=99999),
                       cp("E", "fixed", 100, priority=4, valid_to="2026-01-02", per_user_limit=1),
                       cp("N", "fixed", 100, priority=5, scope="nope", min_spend_cents=100)],
               TODAY, {"L": 1, "E": 1})
        self.assertEqual(r["rejected"], {"L": "E-LIMIT", "M": "E-GROUP", "E": "E-EXPIRED", "N": "E-MIN-SPEND"})

    def test_ac11_result_shape(self):
        r = PC([it("x", 1000)], [cp("A", "fixed", 100, priority=2), cp("B", "fixed", 50, priority=1)], TODAY)
        self.assertEqual(r["applied"], [{"code": "B", "discount": 50}, {"code": "A", "discount": 100}])
        self.assertEqual((r["discount"], r["total"]), (150, 850))

    def test_ac11_unknown_kind(self):
        with self.assertRaises(ValueError) as c:
            PC([it("x", 1000)], [cp("A", "fixed", 100), cp("B", "free", 0, valid_to="2020-01-01")], TODAY)
        self.assertEqual(str(c.exception), "E-KIND")
