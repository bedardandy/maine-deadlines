"""Tests for the jurisdiction-module refactor (generic core + back-compat).

These cover the *new* surface added when Maine law moved behind the portable
``legal_jurisdictions`` contract:

1. **Back-compat**: ``compute`` / ``default_pack`` still Maine-by-default, and the
   pack is now sourced FROM the ``jurisdiction-maine`` module (not a bundled file).
2. **Generic core**: ``compute(..., jurisdiction="US")`` runs the FEDERAL module with
   the federal count-every-day model — the same engine surface, different law.
3. **Maine vs Federal divergence**: the SAME trigger date and period computes to
   DIFFERENT deadlines because Maine excludes intermediate weekends for short (<7d)
   periods while the federal FRCP 6(a) model counts every day.
4. **Silent-wrong doctrine**: an UNPOPULATED module (a ``TO_RESEARCH`` scaffold, the
   New-Hampshire shape) raises :class:`NotVerifiedLawError` loudly — never a silent
   empty result.
"""

import datetime as dt

import pytest

import maine_deadlines as md
from maine_deadlines import NotVerifiedLawError, UnsupportedCountingModelError

# jurisdiction-federal is an optional test-only peer; skip cleanly if absent.
jurisdiction_federal = pytest.importorskip("jurisdiction_federal")

AS_OF = dt.date(2026, 7, 7)


# --- 1. back-compat: Maine-by-default, pack sourced from the module ----------


def test_default_pack_sourced_from_module():
    """The default pack now loads FROM jurisdiction-maine, not a repo-local file."""
    import legal_jurisdictions as lj

    module = lj.load("US-ME")
    pack = md.default_pack()
    assert set(pack.rule_ids()) == {r["id"] for r in module.deadlines.rules}
    # And the classic bundled-file loader still works (public API preserved).
    assert md.RulePack.load(md.DEFAULT_PACK).rule_ids() == pack.rule_ids()


def test_compute_default_is_maine():
    """No jurisdiction= arg → identical historical Maine behavior."""
    r = md.compute("civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)}, as_of=AS_OF)
    assert r.date == dt.date(2026, 1, 26)
    assert r.rule.id == "civil_answer"


# --- 2. generic core: the federal module through the same engine surface -----


def test_compute_federal_via_jurisdiction_arg():
    """The same compute() runs the FEDERAL module when jurisdiction='US'."""
    r = md.compute(
        "frcp_answer",
        {"service_of_complaint": dt.date(2026, 1, 5)},
        jurisdiction="US",
        as_of=AS_OF,
    )
    # 21-day FRCP answer from a Monday: 2026-01-26 (a Monday), no roll needed.
    assert r.date == dt.date(2026, 1, 26)
    assert r.rule.authority.startswith("Fed. R. Civ. P.")
    assert r.inputs["jurisdiction"] == "US"
    # Same DeadlineResult shape as Maine — the point of the generic core.
    assert isinstance(r, md.DeadlineResult)
    assert r.trace.steps


# --- 3. Maine vs Federal divergence (the counting-model contrast) ------------

# A 5-day period from Thursday 2026-06-25 spanning ONE weekend (Sat 6/27, Sun 6/28),
# no holiday in the span — an isolated proof of the exclude vs count-every-day split.
_DIVERGE_START = dt.date(2026, 6, 25)  # Thursday
_DIVERGE_DAYS = 5


def _count_maine_short(start, days):
    """Drive Maine's engine directly for a synthetic <7-day forward period."""
    from maine_deadlines.engine import Profile, count_forward_days
    from maine_deadlines.holidays_me import ClosureCalendar
    from maine_deadlines.result import Trace

    return count_forward_days(
        start, days, profile=Profile.CIVIL, cal=ClosureCalendar(), trace=Trace(), flags=set()
    )


def _count_federal(start, days):
    from jurisdiction_federal import _engine as fed

    return fed.count_forward_days(start, days)


def test_maine_excludes_intermediate_weekend_federal_counts_it():
    """SAME trigger + period → DIFFERENT deadline because the counting models differ.

    Maine (<7d): exclude Sat 6/27 + Sun 6/28 → 5 court-days land on Thu 2026-07-02.
    Federal (FRCP 6(a)): count every day → Thu 6/25 + 5 = Tue 2026-06-30.
    The 2-day gap IS the excluded weekend — the deliberate Maine≠federal contrast.
    """
    maine = _count_maine_short(_DIVERGE_START, _DIVERGE_DAYS)
    federal = _count_federal(_DIVERGE_START, _DIVERGE_DAYS)

    assert maine == dt.date(2026, 7, 2), f"Maine expected 2026-07-02, got {maine}"
    assert federal == dt.date(2026, 6, 30), f"Federal expected 2026-06-30, got {federal}"
    assert maine != federal
    # The difference is exactly the excluded intermediate weekend (2 days).
    assert (maine - federal).days == 2


def test_divergence_profiles_are_labelled_correctly():
    """The modules self-describe their contrasting counting models."""
    import legal_jurisdictions as lj

    me = lj.load("US-ME").profile
    us = lj.load("US").profile
    assert me.count_model == "exclude_intermediate"
    assert me.short_period_threshold == 7
    assert us.count_model == "count_every_day"
    assert us.short_period_threshold is None


# --- 4. silent-wrong doctrine: unpopulated module refuses use ----------------


def _unpopulated_module(code="US-NH"):
    """Build an NH-shaped scaffold module whose deadlines provider is a TO_RESEARCH
    stub — the same not-verified-law shape the New Hampshire scaffold ships."""
    from legal_jurisdictions.contract import (
        AuthorityTable,
        CountingProfile,
        CourtCalendar,
        FormRegistry,
        JurisdictionModule,
        RulePack,
        ServiceRules,
    )

    stub = {"_status": "TO_RESEARCH"}
    return JurisdictionModule(
        code=code,
        name="New Hampshire (scaffold)",
        kind="state",
        verified_as_of=None,
        citations=AuthorityTable.from_records([dict(stub)]),
        deadlines=RulePack({"_status": "TO_RESEARCH", "rules": []}),
        holidays=CourtCalendar(dict(stub)),
        forms=FormRegistry.from_records([dict(stub)]),
        service_rules=ServiceRules(dict(stub)),
        profile=CountingProfile(dict(stub)),
    )


def test_unpopulated_module_raises_not_verified_law_loudly():
    """An unpopulated (NH-shaped) module must refuse use, not return nothing."""
    module = _unpopulated_module()
    assert module.is_populated is False
    with pytest.raises(NotVerifiedLawError):
        module.require_populated()
    # And the generic-core entry point surfaces it, never silent-wrong.
    with pytest.raises(NotVerifiedLawError):
        md.compute_for_module(
            module, "any_rule", {"trigger_event": dt.date(2026, 1, 1)}
        )


def test_resolve_unknown_jurisdiction_raises():
    """A jurisdiction code with no installed module fails loudly (not silent)."""
    from legal_jurisdictions.registry import UnknownJurisdictionError

    with pytest.raises(UnknownJurisdictionError):
        md.compute("x", {"t": dt.date(2026, 1, 1)}, jurisdiction="US-ZZ")


def _populated_state_with_model(count_model):
    """Build a POPULATED state module whose profile declares ``count_model`` — used
    to prove this engine refuses a state whose counting model it does not implement."""
    import legal_jurisdictions as lj
    from legal_jurisdictions.contract import CountingProfile, JurisdictionModule

    maine = lj.load("US-ME")  # borrow Maine's populated providers, swap the profile
    return JurisdictionModule(
        code="US-XX",
        name="Otherstate",
        kind="state",
        verified_as_of=maine.verified_as_of,
        citations=maine.citations,
        deadlines=maine.deadlines,
        holidays=maine.holidays,
        forms=maine.forms,
        service_rules=maine.service_rules,
        profile=CountingProfile(
            {"count_model": count_model, "verified_as_of": maine.verified_as_of}
        ),
    )


def test_populated_state_with_wrong_counting_model_is_refused():
    """A populated state module whose count_model != Maine's exclude_intermediate must
    be REFUSED (silent-wrong doctrine), never computed under Maine's mechanics."""
    other = _populated_state_with_model("count_every_day")
    assert other.is_populated is True  # it IS verified law...
    with pytest.raises(UnsupportedCountingModelError):
        # ...but this engine only implements exclude_intermediate, so it refuses.
        md.compute_for_module(
            other, "civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)}
        )


def test_populated_state_with_maine_model_computes():
    """A state module that DOES declare exclude_intermediate runs on this engine."""
    same = _populated_state_with_model("exclude_intermediate")
    r = md.compute_for_module(
        same, "civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)}, as_of=AS_OF
    )
    assert r.date == dt.date(2026, 1, 26)
