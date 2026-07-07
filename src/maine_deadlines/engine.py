"""The rule-agnostic computation engine.

This module knows Maine's *mechanics* -- it does not know any specific deadline.
It implements:

* **Counting profiles** (civil/criminal/probate share one; appellate is a variant):
  exclude the trigger day; include the last day; if the last day is a
  Saturday/Sunday/court-holiday, roll FORWARD to the next non-Sat/Sun/holiday; and
  for SHORT periods (civil "<7 days"; appellate "6 days or fewer") exclude
  intermediate Saturdays, Sundays, and court holidays from the count. Maine NEVER
  adopted the federal 2009 "count every day" rule -- M.R.Civ.P. 6(a). The appellate
  profile additionally applies the Law Court pre-4pm-closure roll where relevant
  (that timing helper lives in :mod:`maine_deadlines.efiling`; the calendar roll is
  identical here).

* **Statutory month/year anniversary math** (1 M.R.S. Sec. 72(11-C)/Sec. 72(30) via
  Sec. 71(12)): calendar-anniversary arithmetic, NOT day-counting. Only the
  final-day weekend/holiday roll applies. The shorter-month edge (Jan 31 + 1 month)
  is a documented config choice, flagged as uncertain.

* **Service-method modifiers**: mail = +3 days applied BEFORE the weekend/holiday
  roll (Rule 6(c)); e-service = +0 (derived, flagged); overseas answer handled by
  the rule pack as a period override.

* **Backward counting** ("at least N days before X"): conservative -- rolls EARLIER
  and always sets the backward-roll-direction uncertainty flag.

All functions take and append to a :class:`~maine_deadlines.result.Trace` so the
computation is fully auditable.
"""

from __future__ import annotations

import calendar as _cal
import datetime as _dt
from enum import StrEnum

from .holidays_me import ClosureCalendar
from .result import Trace, Uncertainty


class Profile(StrEnum):
    """Counting profile. Civil, criminal, and probate share identical mechanics
    (M.R.Prob.P. 6 incorporates M.R.Civ.P. 6 wholesale). Appellate is a variant
    with the same substance but "6 days or fewer" short-period wording."""

    CIVIL = "civil"
    CRIMINAL = "criminal"
    PROBATE = "probate"
    APPELLATE = "appellate"


# Short-period threshold: the count EXCLUDES intermediate weekends/holidays when the
# nominal period is strictly below this many days. Civil/criminal/probate use "<7"
# (threshold 7). Appellate says "6 days or fewer", i.e. period <= 6, i.e. also < 7 --
# substantively identical -- so a single threshold of 7 serves every profile.
_SHORT_PERIOD_THRESHOLD = 7


def _is_weekend(d: _dt.date) -> bool:
    return d.weekday() >= 5  # Sat=5, Sun=6


def is_court_day(d: _dt.date, cal: ClosureCalendar) -> bool:
    """A day the court/clerk is open: not a weekend and not a court closure."""
    return not _is_weekend(d) and not cal.is_court_holiday(d)


def _closure_flags(d: _dt.date, cal: ClosureCalendar) -> set[Uncertainty]:
    """Uncertainty flags implied by a specific closure date (non-statutory deltas)."""
    flags: set[Uncertainty] = set()
    name = cal.holiday_name(d)
    if name == "Day after Thanksgiving":
        flags.add(Uncertainty.THANKSGIVING_FRIDAY_NONSTATUTORY)
    # A weekday closure that is a fixed holiday observed off a Saturday: the observed
    # Friday is the closure. We detect the Sat->Fri case: if d is a Friday and the
    # nominal holiday (d+1) is a Saturday court holiday name match, it's the obs.
    if name and d.weekday() == 4:  # Friday
        nominal = d + _dt.timedelta(days=1)
        if cal.holiday_name(nominal) == name or _same_fixed_holiday(d, name):
            flags.add(Uncertainty.SATURDAY_FRIDAY_OBSERVANCE_NONSTATUTORY)
    return flags


def _same_fixed_holiday(d: _dt.date, name: str) -> bool:
    """True if ``d`` (a Friday) is the Saturday->Friday observance of a fixed holiday.

    We recompute: a fixed holiday whose nominal date is the Saturday d+1.
    """
    nominal = d + _dt.timedelta(days=1)
    fixed = {
        (1, 1): "New Year's Day",
        (6, 19): "Juneteenth",
        (7, 4): "Independence Day",
        (11, 11): "Veterans Day",
        (12, 25): "Christmas Day",
    }
    return fixed.get((nominal.month, nominal.day)) == name and nominal.weekday() == 5


def roll_forward(
    d: _dt.date, cal: ClosureCalendar, trace: Trace, flags: set[Uncertainty]
) -> _dt.date:
    """Roll ``d`` forward to the next court-open day (Rule 6(a) last-day roll).

    Records each skipped day in ``trace`` and accumulates any non-statutory-closure
    uncertainty flags into ``flags``.
    """
    cur = d
    while not is_court_day(cur, cal):
        if _is_weekend(cur):
            reason = "weekend"
        else:
            reason = f"court holiday ({cal.holiday_name(cur)})"
            flags |= _closure_flags(cur, cal)
        nxt = cur + _dt.timedelta(days=1)
        trace.add("roll", f"{cur.isoformat()} is a {reason}; roll forward", nxt)
        cur = nxt
    return cur


def roll_backward(
    d: _dt.date, cal: ClosureCalendar, trace: Trace, flags: set[Uncertainty]
) -> _dt.date:
    """Roll ``d`` backward to the previous court-open day (conservative backward roll).

    Used for "at least N days before X" deadlines: rolling EARLIER preserves full
    clear notice. ALWAYS caller-flagged with BACKWARD_ROLL_DIRECTION.
    """
    cur = d
    while not is_court_day(cur, cal):
        if _is_weekend(cur):
            reason = "weekend"
        else:
            reason = f"court holiday ({cal.holiday_name(cur)})"
            flags |= _closure_flags(cur, cal)
        prv = cur - _dt.timedelta(days=1)
        trace.add("roll", f"{cur.isoformat()} is a {reason}; roll earlier", prv)
        cur = prv
    return cur


def count_forward_days(
    start: _dt.date,
    days: int,
    *,
    profile: Profile,
    cal: ClosureCalendar,
    trace: Trace,
    flags: set[Uncertainty],
) -> _dt.date:
    """Count a forward day-period per Maine Rule 6(a).

    Mechanics:
      * Exclude the trigger day (start counting from the day AFTER ``start``).
      * Include the last day.
      * For SHORT periods (nominal ``days`` < 7) exclude intermediate Sat/Sun/court
        holidays -- i.e. only court-open days advance the counter.
      * For periods of 7+ days, count every calendar day.
      * Then roll the last day forward off any Sat/Sun/court holiday.

    Returns the rolled deadline date.
    """
    if days < 0:
        raise ValueError("count_forward_days requires days >= 0; use backward helper")

    short = days < _SHORT_PERIOD_THRESHOLD
    trace.add(
        "count",
        f"count {days} day(s) from {start.isoformat()} under {profile.value} profile; "
        f"trigger day excluded; "
        + (
            "SHORT period (<7d): intermediate Sat/Sun/court-holidays excluded"
            if short
            else "period >=7d: every calendar day counted"
        ),
        None,
    )

    cur = start
    if short:
        counted = 0
        while counted < days:
            cur = cur + _dt.timedelta(days=1)
            if is_court_day(cur, cal):
                counted += 1
            else:
                trace.add(
                    "exclude",
                    f"{cur.isoformat()} not counted (intermediate "
                    + ("weekend" if _is_weekend(cur) else f"holiday: {cal.holiday_name(cur)}")
                    + ")",
                    None,
                )
                if not _is_weekend(cur):
                    flags |= _closure_flags(cur, cal)
    else:
        cur = start + _dt.timedelta(days=days)
    trace.add("count", f"nominal last day = {cur.isoformat()}", cur)

    rolled = roll_forward(cur, cal, trace, flags)
    if rolled != cur:
        trace.add("count", f"rolled last day to court-open {rolled.isoformat()}", rolled)
    return rolled


def add_service_days(
    start: _dt.date,
    method: str,
    trace: Trace,
    flags: set[Uncertainty],
) -> _dt.date:
    """Apply a service-method modifier BEFORE the weekend/holiday roll (Rule 6(c)).

    ``method`` in {"mail", "eservice", "hand", "none"}. Mail = +3 calendar days.
    E-service = +0 (DERIVED from Rule 5; flags ESERVICE_ZERO_ADDITION). Hand/none = +0.
    Returns the (unrolled) date after the addition.
    """
    method = (method or "none").lower()
    if method == "mail":
        out = start + _dt.timedelta(days=3)
        trace.add("service_add", "service by mail: +3 days (Rule 6(c)), before roll", out)
        return out
    if method == "eservice":
        flags.add(Uncertainty.ESERVICE_ZERO_ADDITION)
        trace.add(
            "service_add",
            "e-service: +0 days (DERIVED from Rule 5 'complete when transmitted'; "
            "MRECS has no add-on) -- inference, flagged",
            start,
        )
        return start
    if method in ("hand", "none", "", "personal"):
        trace.add("service_add", f"service method '{method}': +0 days", start)
        return start
    raise ValueError(f"unknown service method: {method!r}")


# --- month/year anniversary arithmetic (statutory periods) -------------------


class MonthEndPolicy(StrEnum):
    """How to resolve an anniversary that lands in a too-short month."""

    LAST_DAY_OF_MONTH = "last_day_of_month"  # default (documented, flagged)
    ROLL_TO_NEXT_MONTH = "roll_to_next_month"  # e.g. Jan 31 + 1mo -> Mar 3 (2027)


def add_months(
    start: _dt.date,
    months: int,
    *,
    policy: MonthEndPolicy,
    trace: Trace,
    flags: set[Uncertainty],
) -> _dt.date:
    """Calendar-anniversary month arithmetic (NOT day-counting).

    Sec. 72(11-C) defines a month as a calendar month; Sec. 71(12) applies Rule 6
    day-mechanics ONLY to day periods, so month/year periods are pure anniversary
    math. When the target day-of-month does not exist (Jan 31 + 1mo -> "Feb 31"),
    resolve per ``policy`` and set SHORTER_MONTH_ANNIVERSARY (no Maine authority
    resolves the convention).

    The final-day weekend/holiday roll is applied by the caller (composition layer),
    matching how day periods roll their last day.
    """
    total = (start.year * 12 + (start.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    last_dom = _cal.monthrange(year, month)[1]
    if start.day <= last_dom:
        out = _dt.date(year, month, start.day)
        trace.add(
            "anniversary",
            f"{months}-month anniversary of {start.isoformat()} = {out.isoformat()} "
            "(calendar math, not day-counting)",
            out,
        )
        return out

    # Shorter-month edge.
    flags.add(Uncertainty.SHORTER_MONTH_ANNIVERSARY)
    if policy is MonthEndPolicy.LAST_DAY_OF_MONTH:
        out = _dt.date(year, month, last_dom)
        trace.add(
            "anniversary",
            f"{months}-month anniversary of {start.isoformat()} lands in a short month "
            f"(no day {start.day}); policy=last_day_of_month -> {out.isoformat()} "
            "(UNCERTAIN: no Maine authority resolves this)",
            out,
        )
    else:
        overflow = start.day - last_dom
        out = _dt.date(year, month, last_dom) + _dt.timedelta(days=overflow)
        trace.add(
            "anniversary",
            f"{months}-month anniversary lands in a short month; policy=roll_to_next_month "
            f"-> {out.isoformat()} (UNCERTAIN: no Maine authority resolves this)",
            out,
        )
    return out


def add_years(
    start: _dt.date,
    years: int,
    *,
    policy: MonthEndPolicy,
    trace: Trace,
    flags: set[Uncertainty],
) -> _dt.date:
    """Calendar-anniversary year arithmetic. The only short-month case is
    Feb 29 -> non-leap year, handled via :func:`add_months` (12*years)."""
    return add_months(start, years * 12, policy=policy, trace=trace, flags=flags)


def count_backward_days(
    hearing: _dt.date,
    days: int,
    *,
    cal: ClosureCalendar,
    trace: Trace,
    flags: set[Uncertainty],
) -> _dt.date:
    """Count "at least ``days`` clear days before ``hearing``".

    Maine Rule 6(a) is written for FORWARD periods and never adopted the federal
    count-backward clause; NO Law Court authority resolves direction. The engine
    takes the CONSERVATIVE reading -- ``days`` full clear days before the hearing,
    rolling EARLIER off any weekend/holiday -- and ALWAYS sets
    BACKWARD_ROLL_DIRECTION so the caller cannot miss the ambiguity.
    """
    flags.add(Uncertainty.BACKWARD_ROLL_DIRECTION)
    trace.add(
        "backward",
        f"backward count: at least {days} clear day(s) before hearing {hearing.isoformat()}; "
        "Maine 6(a) is silent on direction (no Law Court authority) -- rolling EARLIER "
        "(conservative: preserves full clear notice)",
        None,
    )
    # "clear days before": exclude the hearing day itself, count back ``days`` days.
    nominal = hearing - _dt.timedelta(days=days)
    trace.add("backward", f"nominal latest date = {nominal.isoformat()}", nominal)
    rolled = roll_backward(nominal, cal, trace, flags)
    if rolled != nominal:
        trace.add("backward", f"rolled earlier to court-open {rolled.isoformat()}", rolled)
    return rolled
