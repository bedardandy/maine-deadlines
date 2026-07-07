"""Month/year anniversary math, shorter-month edge, and backward counting."""

import datetime as dt

import maine_deadlines as md
from conftest import AS_OF
from maine_deadlines import ClosureCalendar, MonthEndPolicy, Uncertainty
from maine_deadlines import engine as eng
from maine_deadlines.result import Trace


def _fresh():
    return Trace(), set()


def test_month_anniversary_is_calendar_not_daycount():
    trace, flags = _fresh()
    out = eng.add_months(dt.date(2026, 1, 15), 3, policy=MonthEndPolicy.LAST_DAY_OF_MONTH, trace=trace, flags=flags)
    assert out == dt.date(2026, 4, 15)
    assert not flags  # clean anniversary, no shorter-month flag


def test_nov30_plus_3mo_anniversary():
    trace, flags = _fresh()
    out = eng.add_months(dt.date(2026, 11, 30), 3, policy=MonthEndPolicy.LAST_DAY_OF_MONTH, trace=trace, flags=flags)
    assert out == dt.date(2027, 2, 28)  # anniversary itself (before any roll)
    assert Uncertainty.SHORTER_MONTH_ANNIVERSARY in flags  # Feb has no day 30


def test_jan31_plus_1mo_shorter_month_default_last_day():
    trace, flags = _fresh()
    out = eng.add_months(dt.date(2026, 1, 31), 1, policy=MonthEndPolicy.LAST_DAY_OF_MONTH, trace=trace, flags=flags)
    assert out == dt.date(2026, 2, 28)  # Feb 2026 last day
    assert Uncertainty.SHORTER_MONTH_ANNIVERSARY in flags


def test_jan31_plus_1mo_roll_to_next_month_policy():
    trace, flags = _fresh()
    out = eng.add_months(dt.date(2026, 1, 31), 1, policy=MonthEndPolicy.ROLL_TO_NEXT_MONTH, trace=trace, flags=flags)
    # Feb 2026 has 28 days; overflow of 3 -> Mar 3
    assert out == dt.date(2026, 3, 3)
    assert Uncertainty.SHORTER_MONTH_ANNIVERSARY in flags


def test_leap_year_feb29_plus_1yr_shorter_month():
    trace, flags = _fresh()
    out = eng.add_years(dt.date(2028, 2, 29), 1, policy=MonthEndPolicy.LAST_DAY_OF_MONTH, trace=trace, flags=flags)
    assert out == dt.date(2029, 2, 28)
    assert Uncertainty.SHORTER_MONTH_ANNIVERSARY in flags


def test_leap_year_feb29_anniversary_via_rulepack():
    # testacy_contest: informal_probate = 2028-02-29, +12mo -> 2029-02-28
    r = md.compute(
        "testacy_contest",
        {"death": dt.date(2020, 1, 1), "informal_probate": dt.date(2028, 2, 29)},
        as_of=AS_OF,
    )
    assert r.date == dt.date(2029, 2, 28)
    assert Uncertainty.SHORTER_MONTH_ANNIVERSARY in r.uncertainty


def test_shorter_month_flag_surfaces_in_result():
    # probate inventory Nov 30 + 3mo hits the shorter-month edge AND rolls off a Sunday.
    r = md.compute("probate_inventory", {"appointment": dt.date(2026, 11, 30)}, as_of=AS_OF)
    assert r.date == dt.date(2027, 3, 1)
    assert Uncertainty.SHORTER_MONTH_ANNIVERSARY in r.uncertainty


def test_backward_clear_days_excludes_both_endpoints():
    # Thu Mar 5 2026 hearing, 2 clear days: filing day AND hearing day excluded, so
    # Tue+Wed are the two full clear days -> latest filing = Mon Mar 2 (hearing-days-1).
    trace, flags = _fresh()
    out = eng.count_backward_days(dt.date(2026, 3, 5), 2, cal=ClosureCalendar(), trace=trace, flags=flags)
    assert out == dt.date(2026, 3, 2)
    assert Uncertainty.BACKWARD_ROLL_DIRECTION in flags


def test_backward_count_rolls_earlier_and_flags():
    trace, flags = _fresh()
    # hearing Mon Mar 2 2026 - 2 clear days -1 = Fri Feb 27 (Sat/Sun rolled earlier).
    out = eng.count_backward_days(dt.date(2026, 3, 2), 2, cal=ClosureCalendar(), trace=trace, flags=flags)
    assert out == dt.date(2026, 2, 27)
    assert Uncertainty.BACKWARD_ROLL_DIRECTION in flags


def test_backward_flag_present_on_rulepack_backward_rule():
    r = md.compute("motion_reply_before_hearing", {"hearing": dt.date(2026, 3, 9)}, as_of=AS_OF)
    assert r.date == dt.date(2026, 3, 6)
    assert Uncertainty.BACKWARD_ROLL_DIRECTION in r.uncertainty
    # the backward-direction ambiguity must be spelled out in the trace
    assert any("silent on direction" in s.detail for s in r.trace.steps)
