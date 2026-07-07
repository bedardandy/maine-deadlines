"""Optional cross-check: the vendored table's fixed/floating CIVIC holidays should
agree with the vacanza `holidays` package for Maine, on the days both cover.

`holidays` is a TEST-ONLY cross-check, never a runtime dependency. The court table
intentionally DIVERGES from civic holidays (it adds the day after Thanksgiving and
uses Saturday->Friday observance), so we compare only the civic-holiday days and
skip the known, documented deltas. Skips cleanly if `holidays` is not installed.
"""

import datetime as dt

import pytest

from maine_deadlines import generated_court_closures

holidays = pytest.importorskip("holidays")

# Court-table entries that are court-administration deltas, NOT civic holidays --
# excluded from the civic cross-check by design.
_COURT_ONLY_NAMES = {"Day after Thanksgiving"}


@pytest.mark.parametrize("year", [2025, 2026, 2027])
def test_court_civic_days_are_recognized_by_holidays_pkg(year):
    me = holidays.UnitedStates(subdiv="ME", years=year, observed=True)
    court = generated_court_closures(year)
    for day, name in court.items():
        if name in _COURT_ONLY_NAMES:
            continue
        # Saturday->Friday observance is a court practice the civic package models as
        # Sat (unobserved) or Mon; only assert that the underlying civic holiday
        # exists in the same MONTH, which is a weak but real corroboration.
        civic_days = {d for d in me if d.year == year}
        same_month = any(d.month == day.month for d in civic_days)
        assert same_month, f"{name} on {day} has no civic holiday in month {day.month}"


def test_fixed_holidays_match_exactly_when_on_a_weekday():
    # New Year 2027 (Fri Jan 1) and Christmas 2025 (Thu Dec 25) fall on weekdays;
    # they must match the civic package's date precisely.
    me25 = holidays.UnitedStates(subdiv="ME", years=2025, observed=True)
    me27 = holidays.UnitedStates(subdiv="ME", years=2027, observed=True)
    assert dt.date(2025, 12, 25) in me25
    assert dt.date(2027, 1, 1) in me27
    assert dt.date(2025, 12, 25) in generated_court_closures(2025)
    assert dt.date(2027, 1, 1) in generated_court_closures(2027)
