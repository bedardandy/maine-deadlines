"""The vendored court-closure table is PINNED here. If a court-schedule delta
changes, these assertions must be updated deliberately (with a re-verify stamp)."""

import datetime as dt

import pytest

from maine_deadlines import VERIFIED_AS_OF, ClosureCalendar, generated_court_closures

# The full 2026 Maine court-closure set (statutory Sec.1051 + court-page deltas),
# verified 2026-07-07 against courts.maine.gov/courts/schedules/holidays.html.
EXPECTED_2026 = {
    dt.date(2026, 1, 1): "New Year's Day",
    dt.date(2026, 1, 19): "Martin Luther King Jr. Day",
    dt.date(2026, 2, 16): "Washington's Birthday",
    dt.date(2026, 4, 20): "Patriots' Day",
    dt.date(2026, 5, 25): "Memorial Day",
    dt.date(2026, 6, 19): "Juneteenth",
    dt.date(2026, 7, 3): "Independence Day",   # Jul 4 Sat -> observed Fri Jul 3
    dt.date(2026, 9, 7): "Labor Day",
    dt.date(2026, 10, 12): "Indigenous Peoples' Day",
    dt.date(2026, 11, 11): "Veterans Day",
    dt.date(2026, 11, 26): "Thanksgiving Day",
    dt.date(2026, 11, 27): "Day after Thanksgiving",  # admin, non-statutory
    dt.date(2026, 12, 25): "Christmas Day",
}


def test_verified_as_of_stamp():
    assert VERIFIED_AS_OF == dt.date(2026, 7, 7)


def test_2026_table_pinned_exactly():
    got = generated_court_closures(2026)
    assert got == EXPECTED_2026, f"table drift:\n got={sorted(got)}\n exp={sorted(EXPECTED_2026)}"


def test_2026_count_is_13():
    assert len(generated_court_closures(2026)) == 13


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_supported_years_have_all_named_holidays(year):
    tbl = generated_court_closures(year)
    # 13 named closures every year (fixed + floating + Thanksgiving Friday).
    assert len(tbl) == 13


def test_july3_2026_observance_is_a_closure():
    cal = ClosureCalendar()
    assert cal.is_court_holiday(dt.date(2026, 7, 3))
    assert cal.holiday_name(dt.date(2026, 7, 3)) == "Independence Day"


def test_new_year_2027_is_a_closure():
    # Jan 1 2027 is a Friday -> a plain fixed closure.
    assert dt.date(2027, 1, 1) in generated_court_closures(2027)


def test_ad_hoc_layer_adds_closure():
    cal = ClosureCalendar.with_ad_hoc([dt.date(2026, 2, 3)])
    assert cal.is_court_holiday(dt.date(2026, 2, 3))
    assert cal.holiday_name(dt.date(2026, 2, 3)) == "ad-hoc closure"


def test_year_outside_pinned_range_still_computes():
    # 2030 not pinned but rules still generate a table.
    tbl = generated_court_closures(2030)
    assert dt.date(2030, 12, 25) in tbl
    assert not ClosureCalendar().is_supported(dt.date(2030, 1, 1))
