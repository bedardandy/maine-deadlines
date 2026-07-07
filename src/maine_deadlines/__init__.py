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
"""

from __future__ import annotations

import datetime as _dt

from .efiling import (
    CourtLevel,
    FileDateResult,
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
    """The bundled Maine v0.1 rule pack (loaded once, cached)."""
    global _DEFAULT_PACK_CACHE
    if _DEFAULT_PACK_CACHE is None:
        _DEFAULT_PACK_CACHE = RulePack.load(DEFAULT_PACK)
    return _DEFAULT_PACK_CACHE


def compute(
    rule_id: str,
    triggers: dict[str, _dt.date],
    *,
    service_method: str = "none",
    calendar: ClosureCalendar | None = None,
    month_end_policy: MonthEndPolicy = MonthEndPolicy.LAST_DAY_OF_MONTH,
    as_of: _dt.date | None = None,
    staleness_horizon_days: int = 365,
) -> DeadlineResult:
    """Compute a deadline against the default Maine v0.1 pack. See
    :meth:`RulePack.compute` for parameter semantics."""
    return default_pack().compute(
        rule_id,
        triggers,
        service_method=service_method,
        calendar=calendar,
        month_end_policy=month_end_policy,
        as_of=as_of,
        staleness_horizon_days=staleness_horizon_days,
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
    "efile_file_date",
    "trial_court_file_date",
    "law_court_file_date",
    "rejection_relation_back_deadline",
    "DEFAULT_PACK",
]
