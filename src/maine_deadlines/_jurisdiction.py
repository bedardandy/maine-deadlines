"""Bridge from ``maine-deadlines`` to the portable jurisdiction-module contract.

This is the internal seam that turns ``maine-deadlines`` from a Maine-hardcoded
engine into a *generic* deadline core that loads its law from a
:class:`legal_jurisdictions.JurisdictionModule`. It is deliberately thin and
private (leading underscore): the public API in :mod:`maine_deadlines` is unchanged.

Two things live here:

* :func:`module_rule_pack` — build a local :class:`~maine_deadlines.rulepack.RulePack`
  from an installed module's ``deadlines`` provider (the DATA now comes from
  ``jurisdiction-maine`` / ``jurisdiction-federal``, not a file bundled in this repo).
* :func:`compute_for_module` — the generic-core dispatch: given a *populated*
  jurisdiction module, compute a deadline with that jurisdiction's OWN counting
  model. Maine keeps Maine's ``exclude_intermediate`` mechanics (this repo's engine);
  a federal (``kind == "federal"``) module runs the federal count-every-day model
  from ``jurisdiction_federal``. A state module NEVER silently inherits federal
  counting, and an unpopulated module raises :class:`NotVerifiedLawError` loudly.
"""

from __future__ import annotations

import datetime as _dt
from functools import cache

from legal_jurisdictions import JurisdictionModule, NotVerifiedLawError
from legal_jurisdictions import load as _load_module
from legal_jurisdictions.contract import CountingProfile, staleness_warning

from .result import DeadlineResult, RuleRef, Trace, Uncertainty
from .rulepack import RulePack

__all__ = [
    "NotVerifiedLawError",
    "UnsupportedCountingModelError",
    "resolve_module",
    "module_rule_pack",
    "compute_for_module",
    "MAINE_CODE",
]

# The Maine module is this package's native jurisdiction; the federal peer is "US".
MAINE_CODE = "US-ME"

# This repo's engine implements exactly ONE state counting model: Maine's
# ``exclude_intermediate`` short-period mechanics. A state module that declares a
# DIFFERENT counting model must NOT be run through this engine (it would silently
# return a plausible-but-wrong date) — that is the silent-wrong sin. Federal is
# handled by its own engine; any other model is refused loudly.
_ENGINE_STATE_COUNT_MODEL = CountingProfile.EXCLUDE_INTERMEDIATE


class UnsupportedCountingModelError(RuntimeError):
    """A populated module uses a counting model this engine does not implement.

    Raised rather than computing a plausible-but-wrong deadline under the wrong
    jurisdiction's mechanics — the same silent-wrong doctrine as NotVerifiedLawError,
    applied to a module that IS populated but whose counting model diverges from the
    one this repo's engine verifiably implements (Maine's ``exclude_intermediate``)."""


@cache
def resolve_module(code: str) -> JurisdictionModule:
    """Resolve an installed jurisdiction module by code, cached.

    Raises :class:`legal_jurisdictions.registry.UnknownJurisdictionError` if the
    module is not installed. Does NOT check population — callers decide when to
    require verified law (compute requires it; discovery may not)."""
    return _load_module(code)


def module_rule_pack(module: JurisdictionModule) -> RulePack:
    """Build a validated :class:`RulePack` from ``module.deadlines`` data.

    This is how ``maine-deadlines`` now sources its rules: FROM the module, not from
    a JSON file vendored in this repo. The engine mechanics stay here; the law lives
    in the module. Fails loudly on an unpopulated module (no silent empty pack)."""
    module.require_populated()
    return RulePack.from_dict(dict(module.deadlines.data))


def compute_for_module(
    module: JurisdictionModule,
    rule_id: str,
    triggers: dict[str, _dt.date],
    *,
    service_method: str = "none",
    as_of: _dt.date | None = None,
    staleness_horizon_days: int = 365,
    **kwargs,
) -> DeadlineResult:
    """Compute a deadline for ``rule_id`` under ``module``'s OWN counting model.

    * A **state** module (``kind == "state"``, e.g. Maine) uses this repo's engine
      and its ``exclude_intermediate`` short-period mechanics via :class:`RulePack`.
    * A **federal** module (``kind == "federal"``, ``code == "US"``) runs the
      FRCP 6(a) count-every-day engine from ``jurisdiction_federal`` — never Maine's
      mechanics. A state module may *reference* the federal peer, but the caller
      passes the federal module explicitly; counting is never silently merged.

    An unpopulated module raises :class:`NotVerifiedLawError` (loud, never
    silent-wrong). The returned :class:`DeadlineResult` has the identical shape for
    every jurisdiction — that is the point of the generic core."""
    module.require_populated()
    if module.kind == "federal":
        return _compute_federal(
            module,
            rule_id,
            triggers,
            service_method=service_method,
            as_of=as_of,
            staleness_horizon_days=staleness_horizon_days,
        )
    # A non-federal (state) module: this repo's engine implements ONLY Maine's
    # ``exclude_intermediate`` mechanics. Refuse a populated state module whose
    # counting model differs — computing it under Maine's engine would be
    # silent-wrong. (Maine itself declares exclude_intermediate, so it passes.)
    model = module.profile.count_model
    if model != _ENGINE_STATE_COUNT_MODEL:
        raise UnsupportedCountingModelError(
            f"module {module.code} declares count_model {model!r}, but this engine "
            f"implements only {_ENGINE_STATE_COUNT_MODEL!r} (Maine's short-period "
            "exclusion). Refusing to compute it under the wrong jurisdiction's "
            "mechanics. Use that jurisdiction's own module/engine."
        )
    # State module with Maine-compatible mechanics: use this repo's engine over the
    # module's rule pack. calendar/month_end_policy Maine-engine options flow through
    # kwargs; the pack carries each rule's authority/source_url + staleness.
    pack = module_rule_pack(module)
    return pack.compute(
        rule_id,
        triggers,
        service_method=service_method,
        as_of=as_of,
        staleness_horizon_days=staleness_horizon_days,
        **kwargs,
    )


def _compute_federal(
    module: JurisdictionModule,
    rule_id: str,
    triggers: dict[str, _dt.date],
    *,
    service_method: str = "none",
    as_of: _dt.date | None = None,
    staleness_horizon_days: int = 365,
) -> DeadlineResult:
    """Run a federal rule through the federal engine, wrapped in the shared
    :class:`DeadlineResult` ledger shape so callers get a uniform return.

    Honors the same staleness semantics as the Maine path: a module older than the
    horizon past its ``verified_as_of`` emits a warning (law amends)."""
    # Import lazily: the federal module is an optional peer, not a hard dependency of
    # the Maine engine. If a caller asks for "US" it must be installed.
    import jurisdiction_federal as _fed

    rule = module.deadlines.rule(rule_id)
    if rule is None:
        available = [r.get("id") for r in module.deadlines.rules]
        raise KeyError(
            f"no rule {rule_id!r} in module {module.code}; available: {available}"
        )
    # Staleness: same first-class treatment as the Maine engine (parity with the
    # historical compute() contract that accepts as_of/staleness_horizon_days).
    staleness_warning(
        module, as_of=as_of or _dt.date.today(), horizon_days=staleness_horizon_days
    )
    trace = Trace()
    for name, date in triggers.items():
        trace.add("trigger", f"{name} = {date.isoformat()}", date)
    trace.add(
        "count",
        f"federal FRCP 6(a) count-every-day model, {rule.get('period')} day(s)",
        None,
    )
    date = _fed.compute(rule, triggers, service_method=service_method)
    trace.add("count", f"computed deadline = {date.isoformat()}", date)
    ruleref = RuleRef(
        id=rule["id"],
        description=rule.get("description", rule["id"]),
        authority=rule.get("authority", ""),
        source_url=rule.get("source_url", ""),
        verified_as_of=_dt.date.fromisoformat(module.deadlines.verified_as_of),
    )
    return DeadlineResult(
        date=date,
        rule=ruleref,
        trace=trace,
        assumptions=(
            "federal count-every-day model (FRCP 6(a)(1)); intermediate weekends/"
            "holidays are COUNTED — the deliberate contrast with Maine",
        ),
        uncertainty=frozenset({Uncertainty.ASSUMES_NO_UNSCHEDULED_CLOSURE}),
        inputs={
            "triggers": {k: v.isoformat() for k, v in triggers.items()},
            "service_method": service_method,
            "jurisdiction": module.code,
            "as_of": (as_of or _dt.date.today()).isoformat(),
        },
    )
