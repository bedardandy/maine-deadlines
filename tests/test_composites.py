"""Composite later-of / earlier-of deadlines (probate)."""

import datetime as dt

import maine_deadlines as md
from conftest import AS_OF
from maine_deadlines import Uncertainty


def test_creditor_known_later_of_publication_wins():
    r = md.compute(
        "creditor_claim_known",
        {
            "death": dt.date(2026, 1, 1),
            "first_publication": dt.date(2026, 2, 1),
            "mailing": dt.date(2026, 2, 1),
        },
        as_of=AS_OF,
    )
    # later_of(4mo pub=Jun1, 60d mail=Apr2) = Jun1; earlier_of(Jun1, 9mo death=Oct1)=Jun1
    assert r.date == dt.date(2026, 6, 1)


def test_creditor_known_mailing_prong_wins_later_of():
    r = md.compute(
        "creditor_claim_known",
        {
            "death": dt.date(2026, 1, 1),
            "first_publication": dt.date(2026, 2, 1),
            "mailing": dt.date(2026, 4, 15),
        },
        as_of=AS_OF,
    )
    # 60d from Apr15 = Jun14 (Sun) -> Jun15; > 4mo pub (Jun1). cap Oct1. -> Jun15
    assert r.date == dt.date(2026, 6, 15)


def test_creditor_known_nine_month_cap_binds():
    r = md.compute(
        "creditor_claim_known",
        {
            "death": dt.date(2026, 1, 1),
            "first_publication": dt.date(2026, 6, 1),
            "mailing": dt.date(2026, 6, 1),
        },
        as_of=AS_OF,
    )
    # later_of would be ~Oct 1 (4mo from Jun1) but 9mo-from-death cap = Oct 1 binds.
    assert r.date == dt.date(2026, 10, 1)


def test_elective_share_later_of_prongs():
    later_death = md.compute(
        "elective_share",
        {"death": dt.date(2026, 1, 1), "probate_of_will": dt.date(2026, 2, 1)},
        as_of=AS_OF,
    )
    assert later_death.date == dt.date(2026, 10, 1)  # 9mo death wins
    later_probate = md.compute(
        "elective_share",
        {"death": dt.date(2026, 1, 1), "probate_of_will": dt.date(2026, 6, 1)},
        as_of=AS_OF,
    )
    assert later_probate.date == dt.date(2026, 12, 1)  # 6mo probate wins


def test_testacy_contest_composite():
    r = md.compute(
        "testacy_contest",
        {"death": dt.date(2026, 1, 1), "informal_probate": dt.date(2028, 6, 1)},
        as_of=AS_OF,
    )
    assert r.date == dt.date(2029, 6, 1)  # 12mo-from-informal-probate wins


def test_composite_trace_shows_fold():
    r = md.compute(
        "creditor_claim_known",
        {
            "death": dt.date(2026, 1, 1),
            "first_publication": dt.date(2026, 2, 1),
            "mailing": dt.date(2026, 2, 1),
        },
        as_of=AS_OF,
    )
    kinds = [s.kind for s in r.trace.steps]
    assert "compose" in kinds
    assert any("later_of" in s.detail for s in r.trace.steps)
    assert any("earlier_of" in s.detail for s in r.trace.steps)


def test_incomplete_rule_is_flagged():
    # cross_appeal encodes only one prong of a "whichever is later" standard.
    r = md.compute("cross_appeal", {"first_notice_of_appeal": dt.date(2026, 4, 22)}, as_of=AS_OF)
    assert Uncertainty.INCOMPLETE_RULE in r.uncertainty
    assert any("only one prong" in a for a in r.assumptions)


def test_court_directed_rules_flagged():
    for rid in ("guardian_annual_report", "conservator_annual_report"):
        r = md.compute(rid, {"appointment": dt.date(2026, 1, 15)}, as_of=AS_OF)
        assert Uncertainty.COURT_DIRECTED_PERIOD in r.uncertainty
