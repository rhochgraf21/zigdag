from __future__ import annotations

from arch import realizes
from arch.model.ids import ComponentId
from arch.model.policy import EffectKind, EffectRule, EffectVerdict, ImportRule, PackageName, Policy
from arch.realize.facts import Effect


def test_effect_vocabularies_stay_equal():
    """The design's effect names and the fact layer's must match (kept separate so facts depend on nothing)."""
    assert {k.value for k in EffectKind} == {e.value for e in Effect} - {"unknown"}


@realizes("arch.model.policy#AC1")
def test_rules_parse_into_typed_policies_and_report_problems():
    policy, problems = Policy.parse({"effects": {"forbid": ["network"], "allow": ["fs.read", "teleport"]}, "colour": 1})
    assert policy.effects.forbid == {EffectKind.NETWORK}
    assert policy.effects.allow == {EffectKind.FS_READ}
    assert any("teleport" in p for p in problems) and any("colour" in p for p in problems)


@realizes("arch.model.policy#AC2")
def test_combination_only_tightens():
    loose = EffectRule(frozenset(), frozenset({EffectKind.FS_READ, EffectKind.STDIO}))
    tight = EffectRule(frozenset({EffectKind.TIME}), frozenset({EffectKind.STDIO}))
    both = EffectRule.combine([loose, tight])
    assert both.verdict(EffectKind.STDIO) is EffectVerdict.PERMITTED
    assert both.verdict(EffectKind.FS_READ) is EffectVerdict.NOT_ALLOWED
    assert both.verdict(EffectKind.TIME) is EffectVerdict.FORBIDDEN


def test_forbids_can_exempt_a_named_subtree():
    from arch.model.ids import ComponentId as C
    policy, problems = Policy.parse({"effects": {"forbid": ["network"], "except_in": ["a.server"]}})
    assert not problems
    assert policy.for_component(C("a.server.http")).effects.verdict(EffectKind.NETWORK) is EffectVerdict.PERMITTED
    assert policy.for_component(C("a.core")).effects.verdict(EffectKind.NETWORK) is EffectVerdict.FORBIDDEN


def test_import_rules_allow_by_scope_and_prefix():
    rule = ImportRule(frozenset({PackageName("ruamel.yaml")}), {ComponentId("a.cli"): frozenset({PackageName("rich")})})
    assert rule.allows(ComponentId("a.core"), PackageName("ruamel.yaml.error"))
    assert not rule.allows(ComponentId("a.core"), PackageName("rich"))
    assert rule.allows(ComponentId("a.cli.render"), PackageName("rich.console"))


def test_policies_describe_themselves_for_review():
    policy, _ = Policy.parse({"effects": {"forbid": ["network"], "except_in": ["a.server"]},
                              "port_types": {"forbid": ["str"], "allow_in_returns": ["bool"]}})
    text = policy.describe()
    assert "forbids effects: network (except in a.server)" in text and "ports may not expose: str" in text
