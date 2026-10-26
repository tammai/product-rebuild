import calendar
import datetime
import math
from fractions import Fraction


def _d(s):
    if not isinstance(s, str) or len(s) != 10:
        raise ValueError("E-DATE")
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        raise ValueError("E-DATE")


def monthly_rate(m):
    if type(m) is not int or m < 0:
        raise ValueError("E-TENURE")
    return 1.0 if m < 12 else (1.25 if m < 60 else 1.75)


def first_month_accrual(join_date):
    d = _d(join_date)
    dim = calendar.monthrange(d.year, d.month)[1]
    return math.floor(Fraction(dim - d.day + 1, dim) * 4) / 4


def working_days(start, end, holidays=(), start_half=False, end_half=False):
    s, e = _d(start), _d(end)
    if e < s:
        raise ValueError("E-RANGE")
    if s == e and start_half and end_half:
        raise ValueError("E-HALF")
    hol = set(holidays)
    total, day = 0.0, s
    while day <= e:
        if day.weekday() < 5 and day.isoformat() not in hol:
            total += 0.5 if (day == s and start_half) or (day == e and end_half) else 1.0
        day += datetime.timedelta(days=1)
    return total


def carry_over(balance):
    if balance < 0:
        return (float(balance), 0.0)
    carried = min(balance, 5.0)
    return (float(carried), float(balance - carried))


def usable_carry(carried, on_date, year):
    return float(carried) if _d(on_date) <= datetime.date(year, 3, 31) else 0.0


def request(balance, carry, start, end, holidays=(), manager_ok=False, start_half=False, end_half=False):
    days = working_days(start, end, holidays, start_half, end_half)
    year = _d(start).year

    def out(status, reason, fc=0.0, fb=0.0, bal=None, car=None):
        return {"status": status, "reason": reason, "days": days, "from_carry": fc, "from_balance": fb,
                "balance_after": float(balance if bal is None else bal),
                "carry_after": float(carry if car is None else car), "start": start}

    if days == 0:
        return out("denied", "E-NO-WORKDAYS")
    fc = min(usable_carry(carry, start, year), days)
    fb = days - fc
    after = balance - fb
    if after < -3.0:
        return out("denied", "E-BALANCE")
    if after < 0 and not manager_ok:
        return out("needs_approval", "E-APPROVAL")
    carry_after = 0.0 if _d(start) > datetime.date(year, 3, 31) else carry - fc
    return out("approved", None, fc, fb, after, carry_after)


def cancel(req, balance, carry, today):
    if req["status"] != "approved":
        raise ValueError("E-STATE")
    year = int(req["start"][:4])
    balance += req["from_balance"]
    if _d(today) <= datetime.date(year, 3, 31):
        carry += req["from_carry"]
    else:
        balance += req["from_carry"]
    return {"balance": float(balance), "carry": float(carry)}
