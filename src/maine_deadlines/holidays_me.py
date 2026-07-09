"""Maine court-closure calendar.

This is NOT a civic-holiday library. It is a *court-closure* calendar: the days
on which Maine state courts (and their clerk's offices) are closed, which is what
Rule 6(a)/45(a) time-computation actually keys on. It is built from two layers:

1. **Statutory legal holidays** -- ``4 M.R.S. Sec. 1051`` (the court legal-holiday
   statute; note it is title 4, NOT title 1). Fixed and floating-Monday rules.
   https://legislature.maine.gov/statutes/4/title4sec1051-1.html

2. **Court-administration deltas** -- published by the Judicial Branch on
   https://www.courts.maine.gov/courts/schedules/holidays.html . These DIVERGE
   from the statute and are authoritative for actual closures. The two deltas we
   vendor are NON-STATUTORY administrative choices:
     - **Thanksgiving Friday** (day after Thanksgiving) is an admin closure.
     - **Saturday-falling holiday observed the preceding Friday** (e.g. Jul 4 2026
       falls on a Saturday -> courts closed Fri Jul 3 2026). ``Sec. 1051`` only
       codifies the Sunday->Monday rollover, so the Saturday->Friday observance is
       an administrative practice.

Both deltas are surfaced as UNCERTAIN in the README: their year-to-year
universality is not guaranteed by statute.

The generated table below is PINNED for 2025-2027 and asserted by tests. It carries
a ``VERIFIED_AS_OF`` stamp. Ad-hoc closures (storm days, Rule 77(c)/Rule 54 clerk-
closure orders) are UNKNOWABLE statically and are supplied at runtime via an
injectable :class:`ClosureCalendar`.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

VERIFIED_AS_OF = _dt.date(2026, 7, 7)

# Years for which the pinned table has been generated and test-pinned.
SUPPORTED_YEARS = (2025, 2026, 2027)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    """The ``n``-th ``weekday`` (Mon=0) of ``month`` in ``year`` (n>=1)."""
    d = _dt.date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + _dt.timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> _dt.date:
    """The last ``weekday`` (Mon=0) of ``month`` in ``year``."""
    if month == 12:
        nxt = _dt.date(year + 1, 1, 1)
    else:
        nxt = _dt.date(year, month + 1, 1)
    last = nxt - _dt.timedelta(days=1)
    return last - _dt.timedelta(days=(last.weekday() - weekday) % 7)


def _fixed_with_observance(year: int, month: int, day: int) -> list[tuple[_dt.date, str]]:
    """A fixed-date holiday plus its court observance.

    Statute rolls Sunday -> Monday. The court page additionally observes a
    Saturday-falling holiday on the preceding Friday. We return the observed
    date(s); the nominal date is not itself a closure unless it lands on a weekday.
    """
    nominal = _dt.date(year, month, day)
    wd = nominal.weekday()
    if wd == 5:  # Saturday -> observed preceding Friday (court-admin, non-statutory)
        return [(nominal - _dt.timedelta(days=1), "obs_fri")]
    if wd == 6:  # Sunday -> observed following Monday (statutory Sec. 1051)
        return [(nominal + _dt.timedelta(days=1), "obs_mon")]
    return [(nominal, "fixed")]


def _statutory_closures(year: int) -> dict[_dt.date, str]:
    """Court legal holidays from 4 M.R.S. Sec. 1051 for ``year``.

    Sundays are legal holidays under the statute but are already excluded by the
    Sat/Sun clause of Rule 6(a); we therefore do NOT enumerate every Sunday here
    (the counting engine excludes weekends independently). We enumerate the named
    holidays and their weekday observances.
    """
    out: dict[_dt.date, str] = {}

    def add(d: _dt.date, name: str) -> None:
        # A named holiday that lands on a weekend is handled by the observance
        # helper; the nominal weekend day itself is already a non-count day.
        out[d] = name

    # Fixed-date holidays (with Sat->Fri / Sun->Mon observance).
    for month, day, name in (
        (1, 1, "New Year's Day"),
        (6, 19, "Juneteenth"),
        (7, 4, "Independence Day"),
        (11, 11, "Veterans Day"),
        (12, 25, "Christmas Day"),
    ):
        for obs_date, _kind in _fixed_with_observance(year, month, day):
            add(obs_date, name)

    # Cross-year New Year's Day: when Jan 1 of the FOLLOWING year falls on a
    # Saturday it is observed the preceding Friday (Dec 31 of THIS year). That
    # observance FALLS in ``year`` even though the holiday is Jan 1 of year+1, so it
    # belongs to — and must be found in — this year's table. Pull in Jan 1 of year+1
    # and keep only the observance(s) whose observed date lands in ``year``.
    for obs_date, _kind in _fixed_with_observance(year + 1, 1, 1):
        if obs_date.year == year:
            add(obs_date, "New Year's Day")

    # Floating-Monday holidays (already always on a Monday).
    add(_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day")
    add(_nth_weekday(year, 2, 0, 3), "Washington's Birthday")  # statutory label
    add(_nth_weekday(year, 4, 0, 3), "Patriots' Day")
    add(_last_weekday(year, 5, 0), "Memorial Day")
    add(_nth_weekday(year, 9, 0, 1), "Labor Day")
    add(_nth_weekday(year, 10, 0, 2), "Indigenous Peoples' Day")

    # Thanksgiving (4th Thursday of November).
    thanksgiving = _nth_weekday(year, 11, 0 + 3, 4)  # Thursday=3
    add(thanksgiving, "Thanksgiving Day")

    return out


def _admin_closures(year: int) -> dict[_dt.date, str]:
    """Non-statutory court-administration closures (courts.maine.gov holidays page).

    Currently: the day after Thanksgiving ("Thanksgiving Friday"). Flagged UNCERTAIN
    in docs -- it is an administrative closure, not codified in Sec. 1051.
    """
    thanksgiving = _nth_weekday(year, 11, 3, 4)  # Thursday=3, 4th
    return {thanksgiving + _dt.timedelta(days=1): "Day after Thanksgiving"}


def generated_court_closures(year: int) -> dict[_dt.date, str]:
    """The full vendored court-closure table for ``year`` (statutory + admin)."""
    out = _statutory_closures(year)
    out.update(_admin_closures(year))
    return out


@dataclass(frozen=True)
class ClosureCalendar:
    """Court-closure calendar with an optional injected ad-hoc layer.

    ``ad_hoc`` holds user-supplied closures that cannot be known statically: storm
    days, Rule 77(c)/Rule 54 clerk-closure orders, or corrections to the vendored
    table. Any date in ``ad_hoc`` is treated as a closure exactly like a vendored
    holiday. Presence of an ad-hoc layer does not by itself remove the
    ``assumes_no_unscheduled_closure`` assumption -- the engine can never prove the
    supplied layer is complete.
    """

    ad_hoc: frozenset[_dt.date] = field(default_factory=frozenset)

    @classmethod
    def with_ad_hoc(cls, dates: object) -> ClosureCalendar:
        return cls(ad_hoc=frozenset(dates or ()))

    def is_court_holiday(self, d: _dt.date) -> bool:
        """True if ``d`` is a vendored or injected court closure (not weekends)."""
        if d in self.ad_hoc:
            return True
        return d in generated_court_closures(d.year)

    def holiday_name(self, d: _dt.date) -> str | None:
        if d in self.ad_hoc:
            return "ad-hoc closure"
        return generated_court_closures(d.year).get(d)

    def is_supported(self, d: _dt.date) -> bool:
        """Whether ``d`` falls in a year with a pinned/verified vendored table."""
        return d.year in SUPPORTED_YEARS
