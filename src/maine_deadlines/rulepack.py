"""Rule pack: DATA loading + the compute dispatcher that maps a rule to the engine.

The rule pack is JSON (``rulepacks/maine_v0_1.json``). Each rule carries its id,
description, authority cite, source URL, ``verified_as_of`` (from the pack), trigger
event name(s), period/unit, profile, and -- for compound deadlines -- a
``composition`` describing a ``later_of``/``earlier_of`` tree over operands. This
module validates the pack against a light structural schema, exposes the rules, and
computes a :class:`~maine_deadlines.result.DeadlineResult` for a given rule id and
trigger dates.

The engine (:mod:`maine_deadlines.engine`) is rule-agnostic; this module is the only
place that knows the shape of the JSON.
"""

from __future__ import annotations

import datetime as _dt
import json
import warnings
from dataclasses import dataclass
from importlib import resources

from . import engine as _eng
from .holidays_me import ClosureCalendar
from .result import DeadlineResult, RuleRef, Trace, Uncertainty

DEFAULT_PACK = "maine_v0_1.json"

# How far past a pack's verified_as_of before results warn about staleness.
DEFAULT_STALENESS_DAYS = 365


class StaleRulePackWarning(UserWarning):
    """Emitted when a rule pack is used more than the staleness horizon past its
    ``verified_as_of`` date. Rules amend; a stale pack may compute wrong dates."""


class RulePackError(ValueError):
    """The pack is structurally invalid, or a requested rule/trigger is missing."""


_ALLOWED_KINDS = {
    "forward_days",
    "forward_months",
    "forward_years",
    "backward_days",
    "composite",
}
_ALLOWED_PROFILES = {p.value for p in _eng.Profile}
_ALLOWED_COMPOSERS = {"later_of", "earlier_of"}


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise RulePackError(msg)


def _validate_operand(op: dict, where: str) -> None:
    _require(isinstance(op, dict), f"{where}: operand must be an object")
    _require(op.get("kind") in {"forward_days", "forward_months", "forward_years"},
             f"{where}: operand kind must be a forward primitive, got {op.get('kind')!r}")
    _require(isinstance(op.get("period"), int) and op["period"] >= 0,
             f"{where}: operand period must be a non-negative int")
    _require(isinstance(op.get("trigger"), str) and op["trigger"],
             f"{where}: operand needs a trigger event name")


def _validate_rule(rule: dict) -> None:
    rid = rule.get("id", "<unknown>")
    for f in ("id", "description", "authority", "source_url", "profile", "kind"):
        _require(isinstance(rule.get(f), str) and rule[f], f"rule {rid}: missing {f!r}")
    _require(rule["kind"] in _ALLOWED_KINDS, f"rule {rid}: bad kind {rule['kind']!r}")
    _require(rule["profile"] in _ALLOWED_PROFILES, f"rule {rid}: bad profile {rule['profile']!r}")
    _require(isinstance(rule.get("test_vectors"), list) and len(rule["test_vectors"]) >= 3,
             f"rule {rid}: needs >=3 test vectors")
    if rule["kind"] == "composite":
        comp = rule.get("composition")
        _require(isinstance(comp, dict), f"rule {rid}: composite needs a composition object")
        _require(comp.get("outer") in _ALLOWED_COMPOSERS,
                 f"rule {rid}: composition.outer must be later_of/earlier_of")
        outer_ops = comp.get("outer_operands", [])
        _require(isinstance(outer_ops, list) and outer_ops,
                 f"rule {rid}: composition needs outer_operands")
        if "inner" in comp:
            _require(comp["inner"] in _ALLOWED_COMPOSERS,
                     f"rule {rid}: composition.inner must be later_of/earlier_of")
            inner_ops = comp.get("inner_operands", [])
            _require(isinstance(inner_ops, list) and inner_ops,
                     f"rule {rid}: composition.inner needs inner_operands")
            for op in inner_ops:
                _validate_operand(op, f"rule {rid} inner")
        for op in outer_ops:
            _validate_operand(op, f"rule {rid} outer")
    else:
        _require(isinstance(rule.get("period"), int) and rule["period"] >= 0,
                 f"rule {rid}: period must be a non-negative int")
        _require(isinstance(rule.get("triggers"), list) and rule["triggers"],
                 f"rule {rid}: needs a triggers list")


@dataclass(frozen=True)
class Rule:
    """A single deadline rule (thin wrapper over the validated dict)."""

    data: dict

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def profile(self) -> _eng.Profile:
        return _eng.Profile(self.data["profile"])

    @property
    def kind(self) -> str:
        return self.data["kind"]

    @property
    def supports_service_method(self) -> bool:
        return bool(self.data.get("supports_service_method"))

    @property
    def triggers(self) -> list[str]:
        if self.kind == "composite":
            comp = self.data["composition"]
            ops = list(comp.get("outer_operands", [])) + list(comp.get("inner_operands", []))
            # de-dup, preserve order
            seen, out = set(), []
            for op in ops:
                t = op["trigger"]
                if t not in seen:
                    seen.add(t)
                    out.append(t)
            return out
        return list(self.data["triggers"])


class RulePack:
    """A loaded, validated rule pack."""

    def __init__(self, data: dict):
        _require(isinstance(data, dict), "pack must be a JSON object")
        _require(isinstance(data.get("rules"), list) and data["rules"],
                 "pack must have a non-empty 'rules' list")
        va = data.get("verified_as_of")
        _require(isinstance(va, str), "pack must carry verified_as_of")
        self.verified_as_of = _dt.date.fromisoformat(va)
        self.pack_id = data.get("pack_id", "<unnamed>")
        self.schema_version = data.get("$schema_version", "0")
        for r in data["rules"]:
            _validate_rule(r)
        self._rules = {r["id"]: Rule(r) for r in data["rules"]}
        self._raw = data

    @classmethod
    def load(cls, name: str = DEFAULT_PACK) -> RulePack:
        """Load a bundled pack by filename from the ``rulepacks`` package data."""
        text = resources.files(f"{__package__}.rulepacks").joinpath(name).read_text("utf-8")
        return cls(json.loads(text))

    @classmethod
    def from_dict(cls, data: dict) -> RulePack:
        return cls(data)

    def rule(self, rule_id: str) -> Rule:
        try:
            return self._rules[rule_id]
        except KeyError:
            raise RulePackError(
                f"no rule {rule_id!r}; available: {sorted(self._rules)}"
            ) from None

    def rule_ids(self) -> list[str]:
        return list(self._rules)

    def _ruleref(self, rule: Rule) -> RuleRef:
        d = rule.data
        return RuleRef(
            id=d["id"],
            description=d["description"],
            authority=d["authority"],
            source_url=d["source_url"],
            verified_as_of=self.verified_as_of,
        )

    def _check_staleness(self, as_of: _dt.date, horizon_days: int) -> None:
        age = (as_of - self.verified_as_of).days
        if age > horizon_days:
            warnings.warn(
                f"rule pack {self.pack_id} verified_as_of {self.verified_as_of.isoformat()} "
                f"is {age} days old (> {horizon_days}-day horizon) as of {as_of.isoformat()}; "
                "Maine rules may have amended -- re-verify against primary sources.",
                StaleRulePackWarning,
                stacklevel=3,
            )

    def compute(
        self,
        rule_id: str,
        triggers: dict[str, _dt.date],
        *,
        service_method: str = "none",
        calendar: ClosureCalendar | None = None,
        month_end_policy: _eng.MonthEndPolicy = _eng.MonthEndPolicy.LAST_DAY_OF_MONTH,
        as_of: _dt.date | None = None,
        staleness_horizon_days: int = DEFAULT_STALENESS_DAYS,
    ) -> DeadlineResult:
        """Compute a :class:`DeadlineResult` for ``rule_id`` and the given triggers.

        ``triggers`` maps trigger event name -> date. ``service_method`` in
        {"mail","eservice","hand","none"} applies only to rules that support it.
        ``calendar`` supplies ad-hoc closures (defaults to the vendored table only).
        ``as_of`` (default today) drives the staleness warning and the year-support
        flag.
        """
        rule = self.rule(rule_id)
        cal = calendar or ClosureCalendar()
        as_of = as_of or _dt.date.today()
        self._check_staleness(as_of, staleness_horizon_days)

        trace = Trace()
        flags: set[Uncertainty] = set()
        assumptions: list[str] = []

        # Validate triggers present.
        for t in rule.triggers:
            _require(
                t in triggers and isinstance(triggers[t], _dt.date),
                f"rule {rule_id}: missing trigger date for {t!r}",
            )
            trace.add("trigger", f"{t} = {triggers[t].isoformat()}", triggers[t])

        if rule.supports_service_method and service_method not in ("none", "", None):
            assumptions.append(f"service method treated as '{service_method}'")
        elif not rule.supports_service_method and service_method not in ("none", "", None):
            raise RulePackError(
                f"rule {rule_id} does not take a service-method modifier"
            )

        if rule.data.get("court_directed"):
            flags.add(Uncertainty.COURT_DIRECTED_PERIOD)
            assumptions.append(
                "period is court-directed; encoded value is a default assumption -- "
                "confirm the court's actual directive"
            )

        date = self._dispatch(
            rule, triggers, service_method, cal, month_end_policy, trace, flags
        )

        # Unscheduled-closure assumption: any forward computation could be shifted by
        # an unknowable ad-hoc closure. Backward computations too (they roll off
        # closures). Always add the assumption + flag; note the injected layer.
        flags.add(Uncertainty.ASSUMES_NO_UNSCHEDULED_CLOSURE)
        if cal.ad_hoc:
            assumptions.append(
                f"{len(cal.ad_hoc)} ad-hoc closure(s) injected; result still assumes no "
                "OTHER unscheduled closure (storm day / Rule 77(c) order)"
            )
        else:
            assumptions.append(
                "assumes no unscheduled court closure (storm day / Rule 77(c) order) "
                "beyond the vendored table"
            )

        if not cal.is_supported(date):
            flags.add(Uncertainty.UNVERIFIED_YEAR)
            assumptions.append(
                f"computed date {date.isoformat()} falls outside pinned holiday-table "
                "years (2025-2027); closures computed from rules but not test-pinned"
            )

        return DeadlineResult(
            date=date,
            rule=self._ruleref(rule),
            trace=trace,
            assumptions=tuple(assumptions),
            uncertainty=frozenset(flags),
            inputs={
                "triggers": {k: v.isoformat() for k, v in triggers.items()},
                "service_method": service_method,
                "month_end_policy": month_end_policy.value,
            },
        )

    # --- dispatch primitives -------------------------------------------------

    def _dispatch(self, rule, triggers, service_method, cal, policy, trace, flags):
        kind = rule.kind
        if kind == "forward_days":
            return self._forward_days(rule, triggers, service_method, cal, trace, flags)
        if kind == "forward_months":
            return self._forward_period(rule, triggers, cal, policy, trace, flags, unit="months")
        if kind == "forward_years":
            return self._forward_period(rule, triggers, cal, policy, trace, flags, unit="years")
        if kind == "backward_days":
            return self._backward_days(rule, triggers, cal, trace, flags)
        if kind == "composite":
            return self._composite(rule, triggers, cal, policy, trace, flags)
        raise RulePackError(f"unhandled kind {kind!r}")  # pragma: no cover

    def _forward_days(self, rule, triggers, service_method, cal, trace, flags):
        start = triggers[rule.triggers[0]]
        days = rule.data["period"]
        if rule.supports_service_method and service_method not in ("none", "", None):
            # Service add extends the period, applied to the nominal last day BEFORE
            # the weekend/holiday roll (Rule 6(c)). So: count without the final roll,
            # add service days, then roll once.
            nominal = start + _dt.timedelta(days=days)
            if days < _eng._SHORT_PERIOD_THRESHOLD:
                # Short-period counting excludes intermediate closures; recompute the
                # unrolled last day via the engine's counter then strip its roll by
                # counting court-days directly.
                nominal = self._short_nominal(start, days, cal, trace, flags)
            else:
                trace.add("count", f"nominal last day (pre-service, pre-roll) = {nominal.isoformat()}", nominal)
            after = _eng.add_service_days(nominal, service_method, trace, flags)
            return _eng.roll_forward(after, cal, trace, flags)
        return _eng.count_forward_days(
            start, days, profile=rule.profile, cal=cal, trace=trace, flags=flags
        )

    @staticmethod
    def _short_nominal(start, days, cal, trace, flags):
        cur, counted = start, 0
        while counted < days:
            cur += _dt.timedelta(days=1)
            if _eng.is_court_day(cur, cal):
                counted += 1
            elif not (cur.weekday() >= 5):
                flags |= _eng._closure_flags(cur, cal)
        trace.add("count", f"short-period nominal last day (pre-service) = {cur.isoformat()}", cur)
        return cur

    def _forward_period(self, rule, triggers, cal, policy, trace, flags, *, unit):
        start = triggers[rule.triggers[0]]
        n = rule.data["period"]
        if unit == "months":
            anniv = _eng.add_months(start, n, policy=policy, trace=trace, flags=flags)
        else:
            anniv = _eng.add_years(start, n, policy=policy, trace=trace, flags=flags)
        return _eng.roll_forward(anniv, cal, trace, flags)

    def _backward_days(self, rule, triggers, cal, trace, flags):
        hearing = triggers[rule.triggers[0]]
        days = rule.data["period"]
        return _eng.count_backward_days(hearing, days, cal=cal, trace=trace, flags=flags)

    def _eval_operand(self, op, triggers, cal, policy, trace, flags):
        start = triggers[op["trigger"]]
        n = op["period"]
        label = op.get("label", op["trigger"])
        trace.add("compose", f"operand: {label}", None)
        if op["kind"] == "forward_days":
            return _eng.count_forward_days(
                start, n, profile=_eng.Profile.PROBATE, cal=cal, trace=trace, flags=flags
            )
        if op["kind"] == "forward_months":
            anniv = _eng.add_months(start, n, policy=policy, trace=trace, flags=flags)
            return _eng.roll_forward(anniv, cal, trace, flags)
        if op["kind"] == "forward_years":
            anniv = _eng.add_years(start, n, policy=policy, trace=trace, flags=flags)
            return _eng.roll_forward(anniv, cal, trace, flags)
        raise RulePackError(f"bad operand kind {op['kind']!r}")  # pragma: no cover

    def _composite(self, rule, triggers, cal, policy, trace, flags):
        comp = rule.data["composition"]
        # Inner composition (if any) yields one value folded into the outer operands.
        outer_values: list[_dt.date] = []
        if "inner" in comp:
            inner_vals = [
                self._eval_operand(op, triggers, cal, policy, trace, flags)
                for op in comp["inner_operands"]
            ]
            inner = self._fold(comp["inner"], inner_vals, trace, "inner")
            outer_values.append(inner)
        for op in comp["outer_operands"]:
            outer_values.append(self._eval_operand(op, triggers, cal, policy, trace, flags))
        return self._fold(comp["outer"], outer_values, trace, "outer")

    @staticmethod
    def _fold(composer, values, trace, where):
        picked = max(values) if composer == "later_of" else min(values)
        trace.add(
            "compose",
            f"{where} {composer} over {[v.isoformat() for v in values]} -> {picked.isoformat()}",
            picked,
        )
        return picked
