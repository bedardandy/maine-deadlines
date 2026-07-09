"""The vendored rule pack (`src/maine_deadlines/rulepacks/maine_v0_1.json`) is a
MIRROR of the authoritative copy that now lives in the ``jurisdiction-maine``
module (``legal_jurisdictions.load("US-ME").deadlines``). Since the refactor,
``default_pack()`` is sourced FROM the module, and the bundled JSON is retained
only for the back-compat ``RulePack.load(DEFAULT_PACK)`` path — so the two can
silently drift.

This test flags that drift. When ``jurisdiction-maine`` is installed we assert a
REAL equality cross-check between the vendored copy and the module source. When it
is not installable in the current test env, we fall back to a self-consistency
check: the vendored file loads, validates, and has the expected shape.
"""

from __future__ import annotations

import json
from importlib import resources

import pytest

from maine_deadlines import DEFAULT_PACK, RulePack


def _load_vendored_raw() -> dict:
    text = resources.files("maine_deadlines.rulepacks").joinpath(DEFAULT_PACK).read_text("utf-8")
    return json.loads(text)


def test_vendored_rulepack_loads_and_validates():
    """Self-consistency: the vendored mirror parses, validates, and is non-empty."""
    raw = _load_vendored_raw()
    assert isinstance(raw, dict)
    assert isinstance(raw.get("rules"), list) and raw["rules"]
    assert isinstance(raw.get("verified_as_of"), str)
    pack = RulePack.load(DEFAULT_PACK)  # runs the structural validator
    assert pack.rule_ids()


def test_vendored_rulepack_mirrors_module_source():
    """Real equality cross-check against the authoritative module copy.

    ``jurisdiction-maine`` owns the rule pack now; the vendored JSON must be a
    byte-for-byte mirror of it (same verified_as_of + identical rule set) so the
    two sources of truth cannot drift apart unnoticed.
    """
    lj = pytest.importorskip("legal_jurisdictions")
    module = lj.load("US-ME")
    vendored = _load_vendored_raw()
    source = dict(module.deadlines.data)

    assert vendored.get("verified_as_of") == source.get("verified_as_of"), (
        "vendored mirror and module source disagree on verified_as_of — "
        "re-sync src/maine_deadlines/rulepacks/maine_v0_1.json from jurisdiction-maine"
    )

    vendored_rules = {r["id"]: r for r in vendored["rules"]}
    source_rules = {r["id"]: r for r in source["rules"]}
    assert set(vendored_rules) == set(source_rules), (
        "vendored mirror and module source have different rule ids — "
        "re-sync the vendored rule pack from jurisdiction-maine"
    )
    for rid in source_rules:
        assert vendored_rules[rid] == source_rules[rid], (
            f"rule {rid!r} drifted between the vendored mirror and the module source"
        )
