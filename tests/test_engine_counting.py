"""Counting-profile mechanics: short-period exclusion, rolls off real 2026 closures,
mail +3 ordering, and the never-adopted federal count-every-day contrast."""

import datetime as dt

import maine_deadlines as md
from conftest import AS_OF
from maine_deadlines import ClosureCalendar, Profile
from maine_deadlines import engine as eng
from maine_deadlines.result import Trace


def _fresh():
    return Trace(), set()


def test_trigger_day_excluded():
    trace, flags = _fresh()
    # 5 days from Wed Jan 7 2026: short period, court days Thu Fri (skip Sat/Sun) Mon Tue Wed
    out = eng.count_forward_days(
        dt.date(2026, 1, 7), 5, profile=Profile.CIVIL, cal=ClosureCalendar(), trace=trace, flags=flags
    )
    # Jan 8(Thu)1 9(Fri)2 [10-11 wknd] 12(Mon)3 13(Tue)4 14(Wed)5
    assert out == dt.date(2026, 1, 14)


def test_short_period_excludes_intermediate_weekend():
    trace, flags = _fresh()
    # 3 days from Fri Jan 9 2026 (short): skip Sat/Sun, count Mon Tue Wed
    out = eng.count_forward_days(
        dt.date(2026, 1, 9), 3, profile=Profile.CIVIL, cal=ClosureCalendar(), trace=trace, flags=flags
    )
    assert out == dt.date(2026, 1, 14)  # Mon12 Tue13 Wed14


def test_short_period_excludes_intermediate_holiday():
    # 3 days from Fri Jul 2 2027. Jul 4 2027 is Sunday -> observed Mon Jul 5 (holiday).
    # Short period excludes Sat/Sun AND that holiday.
    trace, flags = _fresh()
    out = eng.count_forward_days(
        dt.date(2027, 7, 2), 3, profile=Profile.CIVIL, cal=ClosureCalendar(), trace=trace, flags=flags
    )
    # Jul 3(Sat)x 4(Sun)x 5(Mon holiday)x 6(Tue)1 7(Wed)2 8(Thu)3
    assert out == dt.date(2027, 7, 8)


def test_long_period_counts_every_day_not_federal_style():
    # 10 days (>=7) counts every calendar day incl intermediate weekends, then rolls.
    trace, flags = _fresh()
    out = eng.count_forward_days(
        dt.date(2026, 2, 5), 10, profile=Profile.CIVIL, cal=ClosureCalendar(), trace=trace, flags=flags
    )
    # Feb 15 is Sunday -> roll to Mon Feb 16 (which is Washington's Birthday!) -> Tue 17
    assert out == dt.date(2026, 2, 17)


def test_roll_off_real_2026_july3_closure():
    # Jul 4 2026 is a Saturday -> courts observe Fri Jul 3 2026.
    # A deadline landing Fri Jul 3 must roll forward past it (and the weekend) to Mon Jul 6.
    cal = ClosureCalendar()
    assert cal.is_court_holiday(dt.date(2026, 7, 3))
    trace, flags = _fresh()
    # 20 days from Jun 13 2026 = Jul 3 2026 (nominal)
    out = eng.count_forward_days(
        dt.date(2026, 6, 13), 20, profile=Profile.CIVIL, cal=cal, trace=trace, flags=flags
    )
    assert out == dt.date(2026, 7, 6)
    assert md.Uncertainty.SATURDAY_FRIDAY_OBSERVANCE_NONSTATUTORY in flags


def test_mail_plus_three_applied_before_roll():
    # civil answer, mail: nominal last day computed, +3, then single roll.
    r = md.compute(
        "civil_answer",
        {"service_of_complaint": dt.date(2026, 1, 5)},
        service_method="mail",
        as_of=AS_OF,
    )
    # nominal Jan 25 (Sun) + 3 = Jan 28 (Wed), no roll needed
    assert r.date == dt.date(2026, 1, 28)


def test_thanksgiving_friday_flag_when_it_participates():
    # Thanksgiving 2026 = Thu Nov 26; Fri Nov 27 is the admin closure.
    cal = ClosureCalendar()
    assert cal.is_court_holiday(dt.date(2026, 11, 27))
    trace, flags = _fresh()
    # A deadline landing Fri Nov 27 rolls off it -> flag.
    out = eng.roll_forward(dt.date(2026, 11, 27), cal, trace, flags)
    assert out == dt.date(2026, 11, 30)  # Monday
    assert md.Uncertainty.THANKSGIVING_FRIDAY_NONSTATUTORY in flags


def test_injected_ad_hoc_closure_shifts_result():
    storm = dt.date(2026, 1, 26)  # the day civil_answer(Jan 5) lands (a Monday)
    cal = ClosureCalendar.with_ad_hoc([storm])
    r = md.compute(
        "civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)}, calendar=cal, as_of=AS_OF
    )
    # without storm: Jan 26 (Mon). With storm closure on Jan 26 -> Jan 27.
    assert r.date == dt.date(2026, 1, 27)
