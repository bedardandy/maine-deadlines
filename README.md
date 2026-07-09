# maine-deadlines

**Rules-based computation of Maine court deadlines — computed, not docketed.**

> **Disclaimer.** Experimental deadline-computation support for first-draft
> workflows; **computed, not docketed**; not legal advice or a primary source —
> verify every date against current rules. This library is part of an experimental
> Maine legal-automation FOSS suite. Rules amend, courts close for storms, and
> primary authority is silent on several points this library must nonetheless
> resolve (see [Honest uncertainties](#honest-uncertainties)). Treat every output as
> a first draft for a human to check.

`maine-deadlines` computes court deadlines the way Maine's rules actually work — not
the federal way — and it **never returns a bare date**. Every computation returns a
`DeadlineResult` carrying the computed date *plus* its rule id, authority cite,
source URL, `verified_as_of` stamp, a full step-by-step computation trace, an
assumptions list, and machine-readable uncertainty flags.

Python ≥ 3.11. The engine mechanics are pure standard library, but the Maine **law**
(rule pack / holiday table / counting profile / service rules) is no longer vendored
here — it is sourced at runtime from the `jurisdiction-maine` module behind the
`legal-jurisdictions` contract. Both are therefore **runtime dependencies**
(`from maine_deadlines import compute` raises `ModuleNotFoundError` without them); see
[Install / use](#install--use). The optional `jurisdiction-federal` peer is needed
only for `compute(..., jurisdiction="US")`, and `holidays` is a test-only cross-check.

## Why this exists

Across the suite, deadline math had degenerated into naive `+N days`. Deadline
computation is the most malpractice-adjacent logic there is, and a library that
silently rolls the wrong way — or counts a month wrong at month-end — is worse than
no library at all. So the design principle is: **surface the reasoning, flag every
place authority runs out, and make a wrong-but-silent answer structurally
impossible.**

## Install / use

Install the package with its runtime dependencies (`legal-jurisdictions` and
`jurisdiction-maine`, declared in `pyproject.toml` as git peers). From a checkout:

```bash
pip install -e .            # pulls legal-jurisdictions + jurisdiction-maine
pip install -e ".[test]"    # also adds pytest, holidays, jurisdiction-federal
```

Then:

```python
import datetime as dt
from maine_deadlines import compute

r = compute("civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)})
print(r.date)          # 2026-01-26  (20 days -> lands Sunday -> rolls to Monday)
print(r)               # 2026-01-26 [civil_answer / M.R.Civ.P. 12(a)] (uncertainty: ...) -- Computed, not docketed...
for step in r.trace.steps:
    print(step.kind, step.detail)
import json; print(json.dumps(r.as_dict(), indent=2))   # ledger-shaped, serializable
```

Service-by-mail (+3 before the roll), an injectable storm-closure calendar, and
month-end policy are all explicit:

```python
from maine_deadlines import compute, ClosureCalendar, MonthEndPolicy

compute("motion_opposition", {"motion_filing": dt.date(2026, 2, 2)}, service_method="mail")

storm = ClosureCalendar.with_ad_hoc([dt.date(2026, 1, 26)])   # user-supplied closures
compute("civil_answer", {"service_of_complaint": dt.date(2026, 1, 5)}, calendar=storm)
```

## Architecture

**Rule pack = DATA; engine = CODE.** As of the jurisdiction-module refactor the
DATA (rule pack / holiday table / counting profile / service rules) is no longer
vendored here — it lives in the `jurisdiction-maine` module and is loaded through the
`legal-jurisdictions` contract (`legal_jurisdictions.load("US-ME")`). This repo now
ships the rule-*agnostic* engine plus the seam that binds it to a module.

- `engine.py` — the rule-*agnostic* Maine mechanics: counting profiles, weekend/
  holiday rolling, month/year anniversary arithmetic, service-method modifiers,
  backward counting. Knows *how* Maine counts; knows no specific deadline.
- `_jurisdiction.py` — the bridge to the portable jurisdiction-module contract:
  `default_pack()` builds the pack FROM `jurisdiction-maine`, and the generic core
  can compute for any installed module (e.g. `jurisdiction="US"` runs the federal
  count-every-day model via `jurisdiction-federal`).
- `holidays_me.py` — a test-pinned **court-closure** calendar (not a civic holiday
  list) for 2025–2027, generated from `4 M.R.S. §1051` plus the Judicial Branch's
  administrative deltas, `verified_as_of` stamped, with an injectable ad-hoc closure
  layer for storm days / Rule 77(c) orders. Used directly by the engine's roll logic.
- `rulepacks/maine_v0_1.json` — a **back-compat MIRROR** of the authoritative rule
  pack that now lives in `jurisdiction-maine`. It backs the legacy
  `RulePack.load(DEFAULT_PACK)` path only; `default_pack()`/`compute()` source the
  live rules from the module. A test (`tests/test_rulepack_mirror.py`) cross-checks
  the mirror against the module so the two cannot silently drift. Each entry carries
  id, description, authority cite, source URL, `verified_as_of`, trigger event(s),
  period/unit/direction, profile, composition, and **≥ 3 test vectors**.
- `rulepack.py` — loads + structurally validates a pack and dispatches a rule to
  the engine, assembling the `DeadlineResult`.
- `result.py` — `DeadlineResult`, `Trace`, `RuleRef`, `Uncertainty`.
- `efiling.py` — court-level e-filing timing helpers (see below).

### Counting profiles (Maine ≠ federal)

Maine **never adopted** the federal 2009 "count every day" amendment (the 1995
conformity amendment was promulgated, stayed, then permanently withdrawn). So:

- Exclude the trigger day; include the last day.
- Roll the last day **forward** off any Saturday/Sunday/court holiday.
- For **short periods** (civil "< 7 days"; appellate "6 days or fewer" — same
  substance) exclude *intermediate* Saturdays, Sundays, and court holidays.
- **Civil / criminal / probate share one profile** (M.R.Prob.P. 6 incorporates
  M.R.Civ.P. 6 wholesale). **Appellate** is a variant, plus the Law Court's
  pre-4 pm clerk-closure rule for filing timing.

### Statutory month/year periods

`1 M.R.S. §72(11-C)` defines a month as a *calendar* month, and `§71(12)` applies
Rule 6's day-mechanics **only to day periods** — so month/year periods are
anniversary calendar math, **not** day-counting. Only the final-day weekend/holiday
roll applies.

### Composite deadlines are first-class

`later_of` / `earlier_of` over multiple trigger events, e.g. the probate creditor
bar = `earlier_of(9 mo from death, later_of(4 mo publication, 60 d mailing))`
(§3-801/§3-803), the §2-211 elective-share `later_of`, and the §3-108 contest
composite.

### E-filing timing (court-level branch)

- **Trial courts** — MRECS 35(B) midnight rule: timely if transmitted by 11:59:59 pm
  courthouse-local; a weekend/holiday submission takes the next-business-day file
  date; EFS timestamp is determinative.
- **Law Court** — App. 1A / 9(c)(3): clerk-open-day rule + "closed before 4 pm →
  next business day".
- **MRECS 35(F)** rejection relation-back: 4 business days (7 if the notice was
  mailed) — returned as a `RelationBackResult` (never a bare date; carries the
  reasoning and uncertainty flags).

## Rules in v0.1

`civil_answer` (20 days — **not** the federal 21), `civil_answer_overseas` (50),
`answer_after_rule12_denied` (10), `appeal_civil` (21 from docket entry, with
post-judgment-motion reset via trigger replacement), `cross_appeal` (14),
`sj_earliest_filing` (20 from commencement), `motion_opposition` (21),
`motion_reply` (7) + `motion_reply_before_hearing` (≥ 2 days before hearing,
backward), `probate_inventory` (3 mo), `creditor_claim_known` (composite),
`elective_share` (later-of), `testacy_contest` (composite), and the court-directed
`guardian_annual_report` / `conservator_annual_report`.

## Honest uncertainties

The library resolves these because it must, but flags each one — check `result.uncertainty`:

- **Backward-roll direction** (`backward_roll_direction`). Maine 6(a) is written for
  forward periods and never adopted the federal count-backward clause; no Law Court
  authority resolves which way an "N days before hearing" deadline rolls off a
  weekend/holiday. The engine reads "at least N days before" as **N full clear
  days** (both the filing day and the hearing day excluded → latest filing =
  `hearing − N − 1`), then rolls **earlier** off any weekend/holiday. This is the
  conservative reading (preserves full notice); always flagged.
- **Incomplete rule** (`incomplete_rule`). A v0.1 rule that encodes only one prong of
  a multi-prong standard computes that prong alone and says so via this flag and an
  assumption. Currently: `cross_appeal` (later-of; the missing prong could make the
  true deadline *later*) and `motion_reply` (the reply is the *earlier* of 7 days
  from opposition and 2 days before hearing — compute `motion_reply_before_hearing`
  too and take the earlier). Cross-check the missing prong.
- **Shorter-month anniversary** (`shorter_month_anniversary`). No Maine authority
  resolves Jan 31 + 1 month. Default is last-day-of-month (configurable via
  `MonthEndPolicy`); flagged whenever it bites.
- **E-service +0** (`eservice_zero_addition`). Derived from Rule 5 ("complete when
  transmitted") + no MRECS add-on — an inference, not a verbatim rule.
- **Thanksgiving Friday & Saturday→Friday observance**
  (`thanksgiving_friday_nonstatutory`, `saturday_friday_observance_nonstatutory`).
  Court-administration closures, **not** codified in §1051; their year-to-year
  universality is not statutorily guaranteed.
- **Unscheduled closures** (`assumes_no_unscheduled_closure`). Storm days / Rule
  77(c) orders are unknowable statically — supply them via the injectable calendar.
- **Court-directed periods** (`court_directed_period`). Guardian/conservator report
  cadences are court-set; the 12-month value is a default assumption.

## Staleness

A rule pack is stamped `verified_as_of = 2026-07-07`. Used more than a configurable
horizon (default 365 days) past that, computations raise `StaleRulePackWarning` —
Maine rules amend, and a stale pack may compute wrong dates. Re-verify against
primary sources and re-stamp.

## Testing

`pytest` + `ruff`, both clean. Every rule computes every one of its own test vectors
exactly; the vendored holiday table is pinned; short-period exclusion, real-2026
holiday rolls (incl. Fri Jul 3 2026), mail +3, month-end anniversaries, leap-year
anniversaries, backward-count flag assertions, and composites are all covered. An
**optional** test cross-checks the civic-holiday layer against the `holidays` PyPI
package — a test-only convenience, never a runtime dependency; it skips cleanly if
`holidays` is absent.

## License

Apache-2.0. See `LICENSE`.
