"""Result shape ("never a bare date"), assumptions/flags, e-service inference,
staleness warning, and unverified-year flag."""

import datetime as dt

import pytest

import maine_deadlines as md
from conftest import AS_OF
from maine_deadlines import RulePackError, StaleRulePackWarning, Uncertainty


def test_result_is_never_a_bare_date():
    r = md.compute("civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)}, as_of=AS_OF)
    assert isinstance(r, md.DeadlineResult)
    assert isinstance(r.date, dt.date)
    assert r.rule.authority == "M.R.Civ.P. 12(a)"
    assert r.rule.source_url.startswith("http")
    assert r.rule.verified_as_of == dt.date(2026, 7, 7)
    assert r.trace.steps
    assert "Computed, not docketed" in str(r)


def test_result_as_dict_round_trips_fields():
    r = md.compute("civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)}, as_of=AS_OF)
    d = r.as_dict()
    assert d["date"] == r.date.isoformat()
    assert d["rule"]["id"] == "civil_answer"
    assert "disclaimer" in d
    assert isinstance(d["trace"], list) and d["trace"]
    assert isinstance(d["uncertainty"], list)


def test_every_result_carries_unscheduled_closure_assumption():
    r = md.compute("civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)}, as_of=AS_OF)
    assert Uncertainty.ASSUMES_NO_UNSCHEDULED_CLOSURE in r.uncertainty
    assert any("unscheduled" in a for a in r.assumptions)


def test_eservice_zero_addition_is_flagged_as_inference():
    r = md.compute(
        "motion_opposition",
        {"motion_filing": dt.date(2026, 2, 2)},
        service_method="eservice",
        as_of=AS_OF,
    )
    assert Uncertainty.ESERVICE_ZERO_ADDITION in r.uncertainty
    # e-service adds 0 days: same as no service modifier
    plain = md.compute("motion_opposition", {"motion_filing": dt.date(2026, 2, 2)}, as_of=AS_OF)
    assert r.date == plain.date
    assert any("DERIVED" in s.detail for s in r.trace.steps)


def test_mail_adds_three_relative_to_plain():
    plain = md.compute("motion_opposition", {"motion_filing": dt.date(2026, 2, 2)}, as_of=AS_OF)
    mail = md.compute(
        "motion_opposition", {"motion_filing": dt.date(2026, 2, 2)}, service_method="mail", as_of=AS_OF
    )
    assert (mail.date - plain.date).days == 3


def test_service_method_rejected_on_unsupported_rule():
    with pytest.raises(RulePackError):
        md.compute(
            "appeal_civil", {"docket_entry": dt.date(2026, 4, 1)}, service_method="mail", as_of=AS_OF
        )


def test_missing_trigger_raises():
    with pytest.raises(RulePackError):
        md.compute("elective_share", {"death": dt.date(2026, 1, 1)}, as_of=AS_OF)  # missing probate_of_will


def test_unknown_rule_raises():
    with pytest.raises(RulePackError):
        md.compute("no_such_rule", {"x": dt.date(2026, 1, 1)}, as_of=AS_OF)


def test_staleness_warning_past_horizon():
    with pytest.warns(StaleRulePackWarning):
        md.compute(
            "civil_answer",
            {"service_of_complaint": dt.date(2027, 12, 1)},
            as_of=dt.date(2027, 12, 1),  # > 365 days past 2026-07-07
        )


def test_no_staleness_within_horizon():
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", StaleRulePackWarning)
        md.compute(
            "civil_answer",
            {"service_of_complaint": dt.date(2026, 8, 1)},
            as_of=dt.date(2026, 8, 1),
        )


def test_unverified_year_flag_outside_pinned_range():
    # A trigger in 2029 whose result lands 2029 (outside 2025-2027 pinned years).
    r = md.compute(
        "probate_inventory",
        {"appointment": dt.date(2029, 1, 15)},
        as_of=dt.date(2026, 8, 1),  # keep staleness quiet; as_of drives horizon, not trigger
        staleness_horizon_days=100000,
    )
    assert Uncertainty.UNVERIFIED_YEAR in r.uncertainty
