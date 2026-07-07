"""Every rule in the pack must compute every one of its own test vectors exactly."""

import datetime as dt

import pytest

import maine_deadlines as md
from conftest import AS_OF


def _vectors():
    pack = md.default_pack()
    for rid in pack.rule_ids():
        rule = pack.rule(rid)
        for tv in rule.data["test_vectors"]:
            yield pytest.param(rid, tv, id=f"{rid}:{tv['name']}")


@pytest.mark.parametrize("rule_id,tv", list(_vectors()))
def test_rule_vector(rule_id, tv):
    pack = md.default_pack()
    triggers = {k: dt.date.fromisoformat(v) for k, v in tv["trigger"].items()}
    result = pack.compute(
        rule_id,
        triggers,
        service_method=tv.get("service_method", "none"),
        as_of=AS_OF,
    )
    assert result.date.isoformat() == tv["expect"], (
        f"{rule_id}/{tv['name']}: got {result.date} expected {tv['expect']}\n"
        + "\n".join(str(s) for s in result.trace.steps)
    )


def test_every_rule_has_at_least_three_vectors():
    pack = md.default_pack()
    for rid in pack.rule_ids():
        assert len(pack.rule(rid).data["test_vectors"]) >= 3


def test_every_rule_carries_full_provenance():
    pack = md.default_pack()
    for rid in pack.rule_ids():
        d = pack.rule(rid).data
        assert d["authority"]
        assert d["source_url"].startswith("http")
        assert pack.verified_as_of == dt.date(2026, 7, 7)
