"""Result and trace types.

A deadline computation NEVER returns a bare :class:`datetime.date`. It returns a
:class:`DeadlineResult` -- a ledger-shaped record carrying the computed date, the
rule that produced it (id + authority cite + source URL + ``verified_as_of``), a
full step-by-step :class:`Trace`, an ``assumptions`` list, and ``uncertainty``
flags. The framing throughout is *computed, not docketed*: the result is a
first-draft computation to be verified by a human, never an authoritative docket
entry.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import StrEnum


class Uncertainty(StrEnum):
    """Named uncertainty flags a result may carry.

    Each corresponds to a place where Maine primary authority is silent or where
    the engine made a documented-but-unresolved choice. Their presence means: do
    not rely on the computed date without independent verification of this point.
    """

    BACKWARD_ROLL_DIRECTION = "backward_roll_direction"
    """Maine 6(a) is silent on which way a backward ("N days before") period rolls
    off a weekend/holiday, and no Law Court authority resolves it. The engine rolls
    EARLIER (conservative: preserves full clear notice)."""

    SHORTER_MONTH_ANNIVERSARY = "shorter_month_anniversary"
    """A month/year anniversary landed in a month too short for the source day
    (e.g. Jan 31 + 1 month). No Maine authority resolves the convention; the engine
    used its configured default (last-day-of-month)."""

    ESERVICE_ZERO_ADDITION = "eservice_zero_addition"
    """The +0-day treatment of electronic service is DERIVED (Rule 5 "complete when
    transmitted" + MRECS has no add-on); it is an inference, not a verbatim rule."""

    THANKSGIVING_FRIDAY_NONSTATUTORY = "thanksgiving_friday_nonstatutory"
    """A roll/exclusion depended on the day-after-Thanksgiving closure, which is a
    court-administration practice, not codified in 4 M.R.S. Sec. 1051."""

    SATURDAY_FRIDAY_OBSERVANCE_NONSTATUTORY = "saturday_friday_observance_nonstatutory"
    """A roll depended on a Saturday-holiday being observed the preceding Friday,
    which is administrative practice, not codified in Sec. 1051."""

    ASSUMES_NO_UNSCHEDULED_CLOSURE = "assumes_no_unscheduled_closure"
    """Result could be shifted by an unknowable ad-hoc closure (storm day, Rule
    77(c)/54 order) not present in the injected calendar."""

    COURT_DIRECTED_PERIOD = "court_directed_period"
    """The period is set by court direction (e.g. guardian/conservator annual
    reports), not a fixed statutory anniversary; the encoded value is a default
    assumption."""

    UNVERIFIED_YEAR = "unverified_year"
    """A date fell outside the pinned/verified holiday-table years; closures for it
    are computed from rules but not test-pinned."""


@dataclass(frozen=True)
class RuleRef:
    """Identity + provenance of the rule used for a computation."""

    id: str
    description: str
    authority: str  # e.g. "M.R.Civ.P. 12(a)"
    source_url: str
    verified_as_of: _dt.date

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "authority": self.authority,
            "source_url": self.source_url,
            "verified_as_of": self.verified_as_of.isoformat(),
        }


@dataclass(frozen=True)
class TraceStep:
    """One hop in a computation: what happened and to what date.

    ``kind`` is a short machine tag ("trigger", "count", "service_add", "roll",
    "exclude", "compose", "anniversary", "backward"). ``detail`` is human text.
    ``date`` is the running date after this hop (if applicable).
    """

    kind: str
    detail: str
    date: _dt.date | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "date": self.date.isoformat() if self.date else None,
        }


@dataclass
class Trace:
    """Ordered list of computation steps, plus accumulated assumptions/flags."""

    steps: list[TraceStep] = field(default_factory=list)

    def add(self, kind: str, detail: str, date: _dt.date | None = None) -> None:
        self.steps.append(TraceStep(kind, detail, date))

    def as_list(self) -> list[dict]:
        return [s.as_dict() for s in self.steps]


@dataclass(frozen=True)
class DeadlineResult:
    """The ledger-shaped output of every computation.

    Attributes:
        date: the computed deadline date (never returned bare -- always inside this).
        rule: the :class:`RuleRef` that produced it.
        trace: the full :class:`Trace` of hops.
        assumptions: human-readable assumption strings the reader must accept.
        uncertainty: set of :class:`Uncertainty` flags.
        inputs: the trigger dates and options used (echoed for auditability).
    """

    date: _dt.date
    rule: RuleRef
    trace: Trace
    assumptions: tuple[str, ...] = ()
    uncertainty: frozenset[Uncertainty] = frozenset()
    inputs: dict = field(default_factory=dict)

    # "Computed, not docketed" -- a standing reminder rendered in string forms.
    DISCLAIMER = "Computed, not docketed -- verify against current rules; not legal advice."

    def has_flag(self, flag: Uncertainty) -> bool:
        return flag in self.uncertainty

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "rule": self.rule.as_dict(),
            "trace": self.trace.as_list(),
            "assumptions": list(self.assumptions),
            "uncertainty": sorted(u.value for u in self.uncertainty),
            "inputs": {
                k: (v.isoformat() if isinstance(v, _dt.date) else v)
                for k, v in self.inputs.items()
            },
            "disclaimer": self.DISCLAIMER,
        }

    def __str__(self) -> str:
        flags = ", ".join(sorted(u.value for u in self.uncertainty)) or "none"
        return (
            f"{self.date.isoformat()} [{self.rule.id} / {self.rule.authority}] "
            f"(uncertainty: {flags}) -- {self.DISCLAIMER}"
        )
