"""E-filing timing helpers (court-level branch).

Two distinct regimes -- the engine must branch on court level:

* **Trial courts** -- MRECS 35(B): a filing "day" runs 00:00:00 to 11:59:59 pm in
  the courthouse's local time; an e-filing transmitted by 11:59:59 pm is timely, and
  the EFS timestamp is determinative. A submission made on a Saturday, Sunday, or
  court holiday takes a FILE DATE of the next business day. Clerk office hours are
  irrelevant.

* **Law Court** -- M.R.App.P. 9(c)(3) + App. 1A: the clerk-open-day rule applies; a
  filing when the clerk's office is closed before 4:00 pm is timely the next business
  day. Clerk hours DO matter here.

Also: **MRECS 35(F)** rejection relation-back -- a clerk-rejected filing relates back
to its original submission if resubmitted within 4 BUSINESS DAYS of the rejection
notice (7 if the notice was mailed).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from enum import StrEnum

from .engine import is_court_day
from .holidays_me import ClosureCalendar
from .result import Uncertainty


class CourtLevel(StrEnum):
    TRIAL = "trial"
    LAW_COURT = "law_court"


def _next_business_day(d: _dt.date, cal: ClosureCalendar) -> _dt.date:
    cur = d + _dt.timedelta(days=1)
    while not is_court_day(cur, cal):
        cur += _dt.timedelta(days=1)
    return cur


@dataclass(frozen=True)
class FileDateResult:
    """The effective file date of an e-filing plus the reasoning."""

    file_date: _dt.date
    timely: bool
    detail: str
    court_level: CourtLevel

    def __str__(self) -> str:
        return f"{self.file_date.isoformat()} ({self.detail})"


def trial_court_file_date(
    submitted: _dt.datetime,
    *,
    calendar: ClosureCalendar | None = None,
) -> FileDateResult:
    """Effective file date under MRECS 35(B) (trial courts).

    ``submitted`` is a courthouse-local naive datetime (tz is the caller's
    responsibility -- the rule is courthouse-local). A submission at or before
    11:59:59 pm on a court-open day files that day; a submission on a
    weekend/holiday files the next business day.
    """
    cal = calendar or ClosureCalendar()
    day = submitted.date()
    if is_court_day(day, cal):
        return FileDateResult(
            file_date=day,
            timely=True,
            detail=f"submitted {submitted.isoformat()} on a court-open day (<=11:59:59pm); "
            "files same day (MRECS 35(B), EFS timestamp determinative)",
            court_level=CourtLevel.TRIAL,
        )
    nbd = _next_business_day(day, cal)
    return FileDateResult(
        file_date=nbd,
        timely=True,
        detail=f"submitted {submitted.isoformat()} on a "
        + ("weekend" if submitted.weekday() >= 5 else f"court holiday ({cal.holiday_name(day)})")
        + f"; file date = next business day {nbd.isoformat()} (MRECS 35(B))",
        court_level=CourtLevel.TRIAL,
    )


def law_court_file_date(
    submitted: _dt.datetime,
    *,
    clerk_closed_before_4pm: bool = False,
    calendar: ClosureCalendar | None = None,
) -> FileDateResult:
    """Effective file date for the Law Court (App. 9(c)(3) + 1A).

    Clerk-open-day rule: on a weekend/holiday, or when the clerk's office was closed
    before 4:00 pm, the filing is timely the next business day. Unlike the trial
    courts, clerk hours matter, so ``clerk_closed_before_4pm`` can push an otherwise-
    open day's filing to the next business day.
    """
    cal = calendar or ClosureCalendar()
    day = submitted.date()
    open_day = is_court_day(day, cal)
    if open_day and not clerk_closed_before_4pm:
        return FileDateResult(
            file_date=day,
            timely=True,
            detail=f"clerk open {submitted.isoformat()}; files same day (App. 9(c)(3))",
            court_level=CourtLevel.LAW_COURT,
        )
    nbd = _next_business_day(day, cal)
    if not open_day:
        why = "weekend" if submitted.weekday() >= 5 else f"court holiday ({cal.holiday_name(day)})"
    else:
        why = "clerk's office closed before 4:00pm"
    return FileDateResult(
        file_date=nbd,
        timely=True,
        detail=f"{why}; timely next business day {nbd.isoformat()} (App. 1A / 9(c)(3))",
        court_level=CourtLevel.LAW_COURT,
    )


def efile_file_date(
    submitted: _dt.datetime,
    court_level: CourtLevel,
    *,
    clerk_closed_before_4pm: bool = False,
    calendar: ClosureCalendar | None = None,
) -> FileDateResult:
    """Dispatch to the correct court-level file-date helper.

    ``court_level`` is coerced through :class:`CourtLevel` so a bare string
    (``"trial"``) is accepted, and an unrecognized value raises rather than silently
    falling through to the Law Court branch.
    """
    court_level = CourtLevel(court_level)
    if court_level is CourtLevel.TRIAL:
        return trial_court_file_date(submitted, calendar=calendar)
    return law_court_file_date(
        submitted, clerk_closed_before_4pm=clerk_closed_before_4pm, calendar=calendar
    )


@dataclass(frozen=True)
class RelationBackResult:
    """Last day to resubmit a rejected filing so it relates back (MRECS 35(F)).

    Like every computed *deadline* in this library, this is never a bare date: it
    carries the reasoning, assumptions, and uncertainty flags. ``.date`` is the last
    business day to resubmit.
    """

    date: _dt.date
    detail: str
    assumptions: tuple[str, ...] = ()
    uncertainty: frozenset[Uncertainty] = frozenset()

    DISCLAIMER = "Computed, not docketed -- verify against current rules; not legal advice."

    def has_flag(self, flag: Uncertainty) -> bool:
        return flag in self.uncertainty

    def __str__(self) -> str:
        flags = ", ".join(sorted(self.uncertainty)) or "none"
        return f"{self.date.isoformat()} ({self.detail}) [uncertainty: {flags}] -- {self.DISCLAIMER}"


def rejection_relation_back_deadline(
    rejection_notice: _dt.date,
    *,
    notice_mailed: bool = False,
    calendar: ClosureCalendar | None = None,
) -> RelationBackResult:
    """Last day to resubmit so a rejected filing relates back (MRECS 35(F)).

    4 BUSINESS days from the rejection notice (7 if the notice was mailed). Business
    days = court-open days (weekends + court holidays excluded). The rejection-notice
    day itself is not counted. Returns a :class:`RelationBackResult` (never a bare
    date), carrying the unscheduled-closure assumption and, if the result lands
    outside the pinned holiday-table years, the ``unverified_year`` flag.
    """
    cal = calendar or ClosureCalendar()
    n = 7 if notice_mailed else 4
    cur, counted = rejection_notice, 0
    while counted < n:
        cur += _dt.timedelta(days=1)
        if is_court_day(cur, cal):
            counted += 1

    assumptions = [
        "assumes no unscheduled court closure (storm day / Rule 77(c) order) beyond "
        "the vendored/injected calendar"
    ]
    flags = {Uncertainty.ASSUMES_NO_UNSCHEDULED_CLOSURE}
    if not cal.is_supported(cur):
        flags.add(Uncertainty.UNVERIFIED_YEAR)
        assumptions.append(
            f"resubmission date {cur.isoformat()} falls outside the pinned holiday-table "
            "years (2025-2027); closures computed from rules but not test-pinned"
        )
    return RelationBackResult(
        date=cur,
        detail=f"{n} business day(s) from rejection notice {rejection_notice.isoformat()}"
        + (" (mailed +3 -> 7)" if notice_mailed else "")
        + " (MRECS 35(F))",
        assumptions=tuple(assumptions),
        uncertainty=frozenset(flags),
    )
