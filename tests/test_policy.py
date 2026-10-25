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
    c = ComponentId("a.core")
    both = EffectRule.combine([loose, tight], c)
    assert both.verdict(c, EffectKind.STDIO) is EffectVerdict.PERMITTED
    assert both.verdict(c, EffectKind.FS_READ) is EffectVerdict.NOT_ALLOWED
    assert both.verdict(c, EffectKind.TIME) is EffectVerdict.FORBIDDEN


def test_forbids_can_exempt_a_named_subtree():
    from arch.model.ids import ComponentId as C
    policy, problems = Policy.parse({"effects": {"forbid": ["network"], "except_in": ["a.server"]}})
    assert not problems
    assert policy.effects.verdict(C("a.server.http"), EffectKind.NETWORK) is EffectVerdict.PERMITTED
    assert policy.effects.verdict(C("a.core"), EffectKind.NETWORK) is EffectVerdict.FORBIDDEN
    combined = Policy.combine([policy], C("a.server.http"))  # exemptions apply when rules are combined too
    assert combined.effects.verdict(C("a.server.http"), EffectKind.NETWORK) is EffectVerdict.PERMITTED


def test_import_rules_allow_by_scope_and_prefix():
    rule = ImportRule(frozenset({PackageName("ruamel.yaml")}), {ComponentId("a.cli"): frozenset({PackageName("rich")})})
    assert rule.allows(ComponentId("a.core"), PackageName("ruamel.yaml.error"))
    assert not rule.allows(ComponentId("a.core"), PackageName("rich"))
    assert rule.allows(ComponentId("a.cli.render"), PackageName("rich.console"))


def test_policies_describe_themselves_for_review():
    policy, _ = Policy.parse({"effects": {"forbid": ["network"], "except_in": ["a.server"]},
                              "port_types": {"forbid": ["str"], "allow_in_returns": ["bool"]}})
    text = policy.describe()
    assert "Code must not use these effects: network.\nThis does not apply in a.server." in text
    assert "must not take or return these bare types: str." in text and "They may return bool." in text
