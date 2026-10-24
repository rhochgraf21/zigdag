from __future__ import annotations

from arch import realizes
from arch.check import Lexicon, Term, check
from arch.check.engine import Severity
from tests.conftest import component, graph

NEED_WITH_SOLUTION = "---\nkind: need\n---\nShoppers can see products from a Redis cache via the API.\n"


def findings(files, lexicon=Lexicon()):
    return check(graph(files), lexicon=lexicon).findings


def base(**extra):
    return {"needs/n.md": "---\nkind: need\n---\nShoppers can decide before losing interest.\n",
            "components/s.md": component(serves="n"), **extra}


@realizes("arch.check.statements#AC1")
def test_solution_terms_in_needs_quote_the_phrase():
    got = [f for f in findings(base(**{"needs/n.md": NEED_WITH_SOLUTION})) if f.rule == "S101"]
    assert {f.key for f in got} == {"solution:redis", "solution:cache", "solution:via", "solution:api"}
    assert any("'redis'" in f.message for f in got)


def test_vague_and_non_ears_criteria():
    vague = component(serves="n").replace("When asked, it shall do the thing.", "It shall be fast.")
    no_shall = component(serves="n").replace("When asked, it shall do the thing.", "Works when asked.")
    measured = component(serves="n").replace("When asked, it shall do the thing.", "It shall be fast: under 200 ms.")
    assert ("S102", Severity.WARNING) in {(f.rule, f.severity) for f in findings(base(**{"components/s/a.md": vague}))}
    assert "S103" in {f.rule for f in findings(base(**{"components/s/a.md": no_shall}))}
    assert "S102" not in {f.rule for f in findings(base(**{"components/s/a.md": measured}))}


def test_compound_requirements():
    compound = component(serves="n").replace("realizes: Do the thing", "realizes: Store orders and notify buyers")
    nouns = component(serves="n").replace("realizes: Do the thing", "realizes: Price orders and refunds")
    assert "S104" in {f.rule for f in findings(base(**{"components/s/a.md": compound}))}
    assert "S104" not in {f.rule for f in findings(base(**{"components/s/a.md": nouns}))}


@realizes("arch.check.statements#AC2")
def test_lexicons_extend_per_project():
    need = "---\nkind: need\n---\nShoppers can see products in the Widgetron.\n"
    assert not [f for f in findings(base(**{"needs/n.md": need})) if f.rule == "S101"]
    custom = Lexicon().extended(solution=[Term("Widgetron")])
    assert [f.key for f in findings(base(**{"needs/n.md": need}), custom) if f.rule == "S101"] == ["solution:widgetron"]


@realizes("arch.check.statements#AC3")
def test_suppressions_need_reasons_and_are_dropped_when_unused():
    with_reason = "---\nkind: need\nsuppress: {S101: 'the API is what this customer sells'}\n---\nPartners can call the API.\n"
    no_reason = "---\nkind: need\nsuppress: {S101: ''}\n---\nPartners can call the API.\n"
    unused = "---\nkind: need\nsuppress: {S101: 'old reason'}\n---\nPartners can trade.\n"
    assert not {f.rule for f in findings(base(**{"needs/n.md": with_reason}))} & {"S101", "S105"}
    assert {"S101", "S105"} <= {f.rule for f in findings(base(**{"needs/n.md": no_reason}))}
    assert "S106" in {f.rule for f in findings(base(**{"needs/n.md": unused}))}
