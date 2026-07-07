"""maine-deadlines -- rules-based Maine court-deadline computation.

Experimental deadline-computation support for first-draft workflows. **Computed,
not docketed.** Every computation returns a :class:`DeadlineResult` carrying its
rule cite, source URL, ``verified_as_of``, a full computation trace, assumptions,
and uncertainty flags -- never a bare date. This is not legal advice or a primary
source; verify every date against the current rules.

Quick start::

    from maine_deadlines import compute
    import datetime as dt

    r = compute("civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)})
    print(r)          # 2026-01-26 [civil_answer / M.R.Civ.P. 12(a)] (uncertainty: ...)
    print(r.date)     # datetime.date(2026, 1, 26)
    for step in r.trace.steps:
        print(step)

The public surface is intentionally small: :func:`compute` (convenience over the
default pack), :class:`RulePack` (load/validate/compute), the engine primitives,
the closure calendar, and the e-filing helpers.

**Jurisdiction is now a pluggable module.** As of the jurisdiction-module refactor,
the Maine rule pack / holiday table / counting profile / service rules are sourced
FROM the ``jurisdiction-maine`` package (``legal_jurisdictions.load("US-ME")``)
rather than a JSON file vendored here — the entire public API above is unchanged and
still Maine-by-default. :func:`compute` additionally accepts ``jurisdiction=`` so the
same generic engine can compute for ANY installed module (e.g. ``jurisdiction="US"``
runs the FEDERAL count-every-day model via ``jurisdiction-federal`` — deliberately
different from Maine's short-period exclusion). An unpopulated module (a
``TO_RESEARCH`` scaffold) raises :class:`NotVerifiedLawError` loudly — never a
silent-wrong empty result.
"""

from __future__ import annotations

import datetime as _dt

from ._jurisdiction import (
    MAINE_CODE,
    NotVerifiedLawError,
    UnsupportedCountingModelError,
    compute_for_module,
    module_rule_pack,
    resolve_module,
)
from .efiling import (
    CourtLevel,
    FileDateResult,
    RelationBackResult,
    efile_file_date,
    law_court_file_date,
    rejection_relation_back_deadline,
    trial_court_file_date,
)
from .engine import MonthEndPolicy, Profile
from .holidays_me import (
    VERIFIED_AS_OF,
    ClosureCalendar,
    generated_court_closures,
)
from .result import DeadlineResult, RuleRef, Trace, TraceStep, Uncertainty
from .rulepack import (
    DEFAULT_PACK,
    Rule,
    RulePack,
    RulePackError,
    StaleRulePackWarning,
)

__version__ = "0.1.0"

_DEFAULT_PACK_CACHE: RulePack | None = None


def default_pack() -> RulePack:
    """The Maine v0.1 rule pack, now sourced FROM the ``jurisdiction-maine`` module
    (``legal_jurisdictions.load("US-ME")``) rather than a JSON file bundled in this
    repo. Loaded once and cached. The returned :class:`RulePack` and every rule it
    exposes are byte-for-byte the same Maine law as before the refactor — this is a
    back-compat refactor, not a data change."""
    global _DEFAULT_PACK_CACHE
    if _DEFAULT_PACK_CACHE is None:
        _DEFAULT_PACK_CACHE = module_rule_pack(resolve_module(MAINE_CODE))
    return _DEFAULT_PACK_CACHE


def compute(
    rule_id: str,
    triggers: dict[str, _dt.date],
    *,
    jurisdiction: str = MAINE_CODE,
    service_method: str = "none",
    calendar: ClosureCalendar | None = None,
    month_end_policy: MonthEndPolicy = MonthEndPolicy.LAST_DAY_OF_MONTH,
    as_of: _dt.date | None = None,
    staleness_horizon_days: int = 365,
) -> DeadlineResult:
    """Compute a deadline for ``rule_id`` and ``triggers``.

    By default (``jurisdiction="US-ME"``) this is exactly the historical behavior:
    Maine's v0.1 pack computed under Maine's ``exclude_intermediate`` mechanics, with
    ``calendar`` / ``month_end_policy`` / ``as_of`` / staleness semantics identical to
    :meth:`RulePack.compute`.

    Pass ``jurisdiction=`` (any code registered with ``legal_jurisdictions``, e.g.
    ``"US"`` for the federal peer module) to run the *same* generic engine against a
    DIFFERENT jurisdiction's law under THAT jurisdiction's own counting model —
    federal runs the FRCP 6(a) count-every-day model, never Maine's short-period
    exclusion. An unpopulated module raises :class:`NotVerifiedLawError`.

    The ``calendar`` / ``month_end_policy`` options are Maine-engine specifics; they
    are honored for the (default) Maine path and ignored by peer engines that do not
    model them (the federal engine uses its own statutory holiday set)."""
    module = resolve_module(jurisdiction)
    if module.kind == "state" and jurisdiction.upper() == MAINE_CODE:
        # Native fast path: identical to the pre-refactor Maine computation.
        return default_pack().compute(
            rule_id,
            triggers,
            service_method=service_method,
            calendar=calendar,
            month_end_policy=month_end_policy,
            as_of=as_of,
            staleness_horizon_days=staleness_horizon_days,
        )
    # Generic core: any other installed jurisdiction module, its own counting model.
    # calendar/month_end_policy are Maine-engine specifics — forwarded to a
    # Maine-compatible state engine, ignored by a peer (federal) engine that does not
    # model them. staleness/as_of are honored on every path.
    extra = {}
    if module.kind != "federal":
        extra["calendar"] = calendar
        extra["month_end_policy"] = month_end_policy
    return compute_for_module(
        module,
        rule_id,
        triggers,
        service_method=service_method,
        as_of=as_of,
        staleness_horizon_days=staleness_horizon_days,
        **extra,
    )


__all__ = [
    "__version__",
    "compute",
    "default_pack",
    "DeadlineResult",
    "RuleRef",
    "Trace",
    "TraceStep",
    "Uncertainty",
    "RulePack",
    "Rule",
    "RulePackError",
    "StaleRulePackWarning",
    "Profile",
    "MonthEndPolicy",
    "ClosureCalendar",
    "generated_court_closures",
    "VERIFIED_AS_OF",
    "CourtLevel",
    "FileDateResult",
    "RelationBackResult",
    "efile_file_date",
    "trial_court_file_date",
    "law_court_file_date",
    "rejection_relation_back_deadline",
    "DEFAULT_PACK",
    "NotVerifiedLawError",
    "UnsupportedCountingModelError",
    "compute_for_module",
    "resolve_module",
    "MAINE_CODE",
]
