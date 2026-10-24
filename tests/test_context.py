from __future__ import annotations

from pathlib import Path

import pytest

from arch import realize, realizes
from arch.check import check
from arch.integrate.workspace import find
from arch.model.graph import Graph
from arch.realize.facts import Roots, Snapshot, SourcePath
from arch.view.context import UnknownTarget, context
from tests.conftest import NEED, component, graph

G = graph({
    "needs/n.md": NEED,
    "components/s.md": component(serves="n"),
    "components/s/core.md": component(serves="n"),
    "components/s/shell.md": component(serves="n", uses="core"),
})
CODE = {
    "src/s/core.py": "def api(x: int) -> int: ...\ndef _hidden(): ...\n",
    "src/s/shell.py": "from s.core import api\n\ndef main():\n    return api(1)\n",
    "tests/test_core.py": "@realizes('s.core#AC1')\ndef test_api(): ...\n",
}
FACTS = realize.extract(Snapshot({SourcePath(k): v for k, v in CODE.items()}, Roots(("src",), ("tests",))))


def card(target, budget=4000):
    return context(G, FACTS, check(G, FACTS), target, budget)


@realizes("arch.view.context#AC1")
def test_targets_resolve_from_ids_modules_paths_and_lines():
    assert card("s.shell").component == "s.shell"
    assert card("s.core").component == "s.core"
    assert card("src/s/shell.py").component == "s.shell"
    line = card("src/s/shell.py:4")
    assert line.component == "s.shell" and "`main`" in line.focus
    assert "need `n`" in card("s.shell").to_markdown()
    with pytest.raises(UnknownTarget):
        card("tests/test_core.py")
    with pytest.raises(UnknownTarget):
        card("no/such.py")


@realizes("arch.view.context#AC2")
def test_neighbours_appear_only_by_external_spec():
    text = card("s.shell").to_markdown()
    assert "### s.core" in text and "`api(x: int) -> int`" in text
    assert "_hidden" not in text
    assert "s.core#AC1" not in text and "tests.test_core" not in text  # the neighbour's criteria and evidence stay out
    assert "evidence: tests.test_core.test_api" in card("s.core").to_markdown()


@realizes("arch.view.context#AC3")
def test_over_budget_compacts_then_drops_lowest_priority_first():
    wide = {**CODE, "src/s/core.py": "".join(f"def api_{i}(x: int) -> int: ...\n" for i in range(12))}
    facts = realize.extract(Snapshot({SourcePath(k): v for k, v in wide.items()}, Roots(("src",), ("tests",))))

    def card(target, budget):
        return context(G, facts, check(G, facts), target, budget)

    full = card("s.shell", budget=100_000)
    priority = {s.title: s.priority for s in full.sections}
    assert not full.omitted and {"May use", "Used by"} - set(priority) == {"Used by"}  # nothing uses shell

    compacted = card("s.shell", budget=full.tokens - 1)
    assert compacted.compacted == ("May use",) and not compacted.omitted  # shortened before anything is dropped

    for budget in range(full.tokens - 1, 0, -10):
        c = card("s.shell", budget=budget)
        dropped = [priority[t] for t in c.omitted]
        assert dropped == sorted(dropped, reverse=True)  # lowest priority goes first
        assert c.sections[0].title == "Component"  # never dropped
        if c.omitted:
            assert "omitted:" in c.to_markdown()


@realizes("arch.view.context#AC4")
def test_small_components_of_arch_fit_the_default_budget():
    ws = find(Path(__file__).parent)
    g = Graph(ws.design())
    facts = ws.facts()
    report = check(g, facts)
    for cid in g.ids():
        c = context(g, facts, report, cid)
        port = sum(1 for line in next((s.lines for s in c.sections if s.title == "Port"), ()) if line.startswith("- `"))
        if port <= 10 and len(g.uses(cid)) <= 5:
            assert c.omitted == () and c.compacted == (), (cid, c.tokens)
