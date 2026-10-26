import importlib.util
import os
import re
import unittest

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(task, off):
    spec = importlib.util.spec_from_file_location("h_" + task, os.path.join(_BASE, task, "hidden_test.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    ns = {}
    for name in dir(m.T):
        k = re.match(r"test_ac(\d+)_", name)
        if k:
            ns[re.sub(r"test_ac\d+_", "test_ac%d_" % (int(k.group(1)) + off), name)] = getattr(m.T, name)
    return type("T_" + task, (unittest.TestCase,), ns)


T_shipping = _load("shipping", 0)
T_coupons = _load("coupons", 11)
T_leave = _load("leave", 22)
