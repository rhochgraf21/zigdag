from __future__ import annotations

import itertools

from hypothesis import given
from hypothesis import strategies as st

from arch import realize, realizes
from arch.change import apply
from arch.change.diff import diff
from arch.change.ops import Link, Relation, SetField, Settable
from arch.check import check
from arch.integrate.cli import main
from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import ComponentId, DesignPath, Ref, Text
from arch.realize.facts import Roots, Snapshot, SourcePath
from arch.view.diagram import (
    DiagramFormat, DiagramView, EdgeKind, Edges, EffectClass, Mark, changes, containment, with_effects, with_observed,
)
from arch.view.diagram.model import _transitive_reduction
from arch.view.outline import Depth
from tests.conftest import NEED, component, graph

FILES = {
    "needs/n.md": NEED,
    "components/s.md": component(serves="n"),
    "components/s/a.md": component(serves="n"),
    "components/s/b.md": component(serves="n", uses="a"),
    "components/s/c.md": component(serves="n", uses="a, b"),
    "components/s/c/x.md": component(),
    "components/s/c/y.md": component(uses="x"),
}
G = graph(FILES)


def closure(edges):
    succ = {}
    for a, b in edges:
        succ.setdefault(a, set()).add(b)
    out = set()
    for start in succ:
        todo, seen = [start], set()
        while todo:
            for y in succ.get(todo.pop(), ()):
                if y not in seen:
                    seen.add(y)
                    todo.append(y)
        out |= {(start, y) for y in seen}
    return out


@realizes("arch.view.diagram#AC5")
@given(st.sets(st.sampled_from([(a, b) for a, b in itertools.permutations("abcdef", 2) if a > b])))
def test_transitive_reduction_keeps_reachability_and_nothing_more(edges):
    reduced = _transitive_reduction(set(edges))
    assert closure(reduced) == closure(edges)
    assert all(closure(reduced - {e}) != closure(edges) for e in reduced)  # every kept edge is needed


def test_containment_nests_and_reduces():
    d = containment(G, ComponentId("s"), Depth(2))
    assert [n.id for n in d.nodes] == ["s.a", "s.b", "s.c"]
    assert [k.id for k in d.nodes[2].children] == ["s.c.x", "s.c.y"]
    pairs = {(e.source, e.target) for e in d.edges}
    assert ("s.c", "s.a") not in pairs and {("s.c", "s.b"), ("s.b", "s.a"), ("s.c.y", "s.c.x")} <= pairs
    assert ("s.c", "s.a") in {(e.source, e.target) for e in containment(G, ComponentId("s"), edges=Edges.ALL).edges}


@realizes("arch.view.diagram#AC1", "arch.view.diagram#AC7")
def test_renderings_are_deterministic_and_share_the_model():
    d = containment(G, ComponentId("s"), Depth(2))
    md = DiagramView(d).to_markdown()
    assert md.startswith("```mermaid\nflowchart LR") and md == DiagramView(containment(G, ComponentId("s"), Depth(2))).to_markdown()
    assert 'subgraph n_s__c["c"]' in md and "n_s__c --> n_s__b" in md
    dot = DiagramView(d, DiagramFormat.DOT).to_markdown()
    assert dot.startswith("digraph arch {") and 'subgraph "cluster_s.c"' in dot and 'ltail="cluster_s.c"' in dot


CODE = {"src/s/__init__.py": "", "src/s/a.py": "import os\n\ndef f():\n    return os.environ\n",
        "src/s/b.py": "from s import a\n", "src/s/c/__init__.py": "", "src/s/c/x.py": "",
        "src/s/c/y.py": "import s.c.x\n", "src/s/stray.py": ""}


def facts(code=CODE):
    return realize.extract(Snapshot({SourcePath(k): v for k, v in code.items()}, Roots(("src",), ())))


@realizes("arch.view.diagram#AC6")
def test_effects_overlay_classifies_parts():
    pure = "---\nkind: constraint\napplies_to: [s.a]\nrule:\n  effects:\n    allow: []\n---\nPure.\n"
    g = graph({**FILES, "constraints/p.md": pure})
    f = facts()
    d = with_effects(containment(g, ComponentId("s")), g, f, check(g, f))
    assert {n.id: n.effect for n in d.nodes} == {"s.a": EffectClass.VIOLATING, "s.b": EffectClass.PURE, "s.c": EffectClass.PURE}
    g2 = graph(FILES)
    d2 = with_effects(containment(g2, ComponentId("s")), g2, f, check(g2, f))
    assert d2.nodes[0].effect is EffectClass.EFFECTFUL


@realizes("arch.view.diagram#AC4")
def test_observed_overlay_adds_undeclared_imports():
    code = {**CODE, "src/s/a.py": "import s.b\n"}  # a imports b, which the design does not declare
    d = with_observed(containment(G, ComponentId("s")), G, facts(code))
    assert any(e.kind is EdgeKind.UNDECLARED and (e.source, e.target) == ("s.a", "s.b") for e in d.edges)


@realizes("arch.view.diagram#AC2")
def test_change_diagram_shows_only_changes_and_neighbours():
    before = codec.load({DesignPath(k): v for k, v in FILES.items()})
    after = apply(before, [SetField(Text("s.b"), Settable.REALIZES, Text("Do b differently")),
                           Link(ComponentId("s.c.y"), Relation.USES, Ref("a"))]).after
    d = changes(Graph(before), Graph(after), diff(before, after))
    marks = {n.id: n.mark for n in d.nodes}
    assert marks["s.b"] is Mark.CHANGED and marks["s.c.y"] is Mark.CHANGED and marks["s.a"] is Mark.UNCHANGED
    assert "s.c.x" in marks and "s" not in marks
    assert any((e.source, e.target, e.mark) == ("s.c.y", "s.a", Mark.ADDED) for e in d.edges)
    assert all(e.source in ("s.b", "s.c.y") or e.target in ("s.b", "s.c.y") for e in d.edges)  # only edges about the change


def test_cli_draws(tmp_path, capsys):
    for path, text in {**{f"design/{k}": v for k, v in FILES.items()}, **CODE}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    assert main(["--project", str(tmp_path), "diagram", "--depth", "2", "--effects", "--format", "mermaid"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("flowchart LR") and "classDef effectful" in out
