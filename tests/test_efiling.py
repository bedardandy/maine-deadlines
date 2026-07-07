"""E-filing timing helpers: trial-court midnight rule, Law Court pre-4pm, and
MRECS 35(F) rejection relation-back."""

import datetime as dt

from maine_deadlines import ClosureCalendar, CourtLevel
from maine_deadlines.efiling import (
    efile_file_date,
    law_court_file_date,
    rejection_relation_back_deadline,
    trial_court_file_date,
)


def test_trial_court_before_midnight_files_same_day():
    r = trial_court_file_date(dt.datetime(2026, 1, 6, 23, 59, 59))
    assert r.file_date == dt.date(2026, 1, 6)
    assert r.timely


def test_trial_court_weekend_submission_files_next_business_day():
    # Sat Jan 10 2026 -> Mon Jan 12
    r = trial_court_file_date(dt.datetime(2026, 1, 10, 15, 0, 0))
    assert r.file_date == dt.date(2026, 1, 12)


def test_trial_court_holiday_submission_rolls():
    # Fri Jul 3 2026 is a court closure (Jul 4 Sat observed) -> next business Mon Jul 6
    r = trial_court_file_date(dt.datetime(2026, 7, 3, 10, 0, 0))
    assert r.file_date == dt.date(2026, 7, 6)


def test_law_court_open_day_files_same_day():
    r = law_court_file_date(dt.datetime(2026, 1, 6, 10, 0, 0))
    assert r.file_date == dt.date(2026, 1, 6)


def test_law_court_closed_before_4pm_rolls_next_business_day():
    # Open weekday but clerk closed before 4pm -> next business day (App. 1A/9(c)(3)).
    r = law_court_file_date(dt.datetime(2026, 1, 6, 15, 0, 0), clerk_closed_before_4pm=True)
    assert r.file_date == dt.date(2026, 1, 7)


def test_dispatch_by_court_level():
    trial = efile_file_date(dt.datetime(2026, 1, 10, 15, 0, 0), CourtLevel.TRIAL)
    assert trial.court_level is CourtLevel.TRIAL
    law = efile_file_date(dt.datetime(2026, 1, 6, 15, 0, 0), CourtLevel.LAW_COURT, clerk_closed_before_4pm=True)
    assert law.court_level is CourtLevel.LAW_COURT


def test_rejection_relation_back_4_business_days():
    # Notice Mon Jan 5 2026 + 4 business days = Fri Jan 9
    d = rejection_relation_back_deadline(dt.date(2026, 1, 5))
    assert d == dt.date(2026, 1, 9)


def test_rejection_relation_back_7_if_mailed():
    # Notice Mon Jan 5 2026 + 7 business days spanning a weekend -> Wed Jan 14
    d = rejection_relation_back_deadline(dt.date(2026, 1, 5), notice_mailed=True)
    assert d == dt.date(2026, 1, 14)


def test_rejection_relation_back_skips_holiday():
    # Notice Fri Jul 2 2027 (Jul 5 Mon holiday). 4 business days: Jul 6,7,8,9 -> Fri Jul 9
    cal = ClosureCalendar()
    d = rejection_relation_back_deadline(dt.date(2027, 7, 2), calendar=cal)
    assert d == dt.date(2027, 7, 9)
