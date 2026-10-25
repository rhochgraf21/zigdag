from __future__ import annotations

from arch import realize, realizes
from arch.check import check
from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import DesignPath
from arch.realize.facts import Roots, Snapshot, SourcePath
from tests.conftest import NEED, component, graph

# a part whose interface is as large as what it hides: eight one-line functions
SHALLOW = "\n".join(f"def f{i}(a: A, b: B) -> C:\n    return a" for i in range(8)) + "\n"
DEEP = "def f(a: A) -> C:\n" + "".join(f"    a = step{i}(a)\n" for i in range(40)) + "    return a\n"


def report(code, part):
    design = Graph(codec.load({DesignPath("needs/n.md"): NEED, DesignPath("components/s.md"): component(serves="n"),
                               DesignPath("components/s/a.md"): part}))
    snap = Snapshot({SourcePath("src/s/__init__.py"): "", SourcePath("src/s/a.py"): code}, Roots(("src",), ()))
    return check(design, realize.extract(snap))


@realizes("arch.check.quality#AC3")
def test_a_part_that_hides_a_decision_behind_a_wide_interface_is_questioned():
    shallow = report(SHALLOW, component(serves="n"))
    (q,) = [f for f in shallow.findings if f.rule == "C016"]
    assert "16 lines behind an interface of 24" in q.message  # 8 functions with 2 parameters each and shallow.severity(q).value == "warning"
    assert not any(f.rule == "C016" for f in report(DEEP, component(serves="n")).findings)
    rule = component(serves="n", hides=None).replace("status:", "publishes: The shared vocabulary\nstatus:")
    assert not any(f.rule == "C016" for f in report(SHALLOW, rule).findings)  # a design rule is judged by stability


@realizes("arch.model.schema#AC6", "arch.check.structure#AC3")
def test_a_part_states_what_it_hides_or_what_it_publishes():
    base = {"needs/n.md": NEED, "components/s.md": component(serves="n")}
    nothing = graph({**base, "components/s/a.md": component(serves="n", hides=None)})
    assert any(f.rule == "S006" for f in check(nothing).findings)
    published = component(serves="n", hides=None).replace("status:", "publishes: The names everyone uses\nstatus:")
    g = graph({**base, "components/s/a.md": published})
    assert not any(f.rule == "S006" for f in check(g).findings) and g["s.a"].publishes == "The names everyone uses"


SMELLS = '''import enum
from dataclasses import dataclass
from typing import Protocol


class Mode(enum.Enum):
    A = "a"
    B = "b"


@dataclass
class Input:
    name: N
    path: P
    size: S
    owner: O


def run(inp: Input, mode: Mode) -> R:
    if mode is Mode.A:
        return inp.name
    return inp.name


def whole(inp: Input) -> R:
    return keep(inp)


class Store(Protocol):
    def load(self, key: K) -> V: ...


class FileStore:
    def load(self, key: K) -> V:
        return key
'''


@realizes("arch.check.quality#AC4", "arch.check.quality#AC5", "arch.check.quality#AC6")
def test_control_parameters_narrow_interfaces_and_single_implementations_are_questioned():
    found = {(f.rule, f.key) for f in report(SMELLS, component(serves="n")).findings if f.rule in ("C017", "C018", "C019")}
    assert ("C017", "control:s.a.run:mode") in found  # `mode` picks what run does
    assert ("C018", "narrow:s.a.run:inp") in found  # reads only inp.name of a four-field Input
    assert not any(k.startswith("narrow:s.a.whole") for _, k in found)  # passes the whole Input on: fine
    assert ("C019", "single:s.a.Store") in found  # one class defines all of Store's methods


@realizes("arch.view.context#AC5")
def test_the_card_says_what_deleting_a_part_would_touch():
    from arch.view.context import context

    design = Graph(codec.load({DesignPath("needs/n.md"): NEED, DesignPath("components/s.md"): component(serves="n"),
                               DesignPath("components/s/a.md"): component(serves="n"),
                               DesignPath("components/s/b.md"): component(serves="n", uses="a")}))
    snap = Snapshot({SourcePath("src/s/__init__.py"): "", SourcePath("src/s/a.py"): "def f() -> X: ...\n",
                     SourcePath("src/s/b.py"): "from s.a import f\n", SourcePath("tests/test_a.py"): "from s.a import f\n"},
                    Roots(("src",), ("tests",)))
    facts = realize.extract(snap)
    card = context(design, facts, check(design, facts), "s.a").to_markdown()
    assert "**Deleting it touches:** 1 file in 1 other component and tests" in card
