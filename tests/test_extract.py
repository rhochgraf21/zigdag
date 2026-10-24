from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from arch import realizes
from arch.realize.facts import Capability, Role, SourcePath, UnitName
from arch.realize.python.extract import extract

SRC = '''
from __future__ import annotations
import os, deal
from deal import pre as require
from . import sibling
from .. import cousin
from ..pkg.mod import thing
from arch.model import codec

__all__ = ["api", "Port"]

def api(x: int) -> int:
    import json
    return x

def hidden(): ...

class Port(Base):
    @deal.has()
    @deal.ensure(lambda self, result: result >= 0)
    def run(self, n: int) -> int: ...
    def _private(self): ...

@require(lambda n: n > 0)
@realizes("a.b#AC1", "a.c")
def checked(n): ...
'''


def facts(text=SRC, path="src/pkg/sub/mod.py", unit="pkg.sub.mod"):
    return extract(SourcePath(path), text, UnitName(unit), Role.SOURCE)


@realizes("arch.realize.python.extract#AC4")
def test_imports_resolve_relative_and_from_forms():
    targets = sorted(i.target for i in facts().imports)
    assert targets == sorted([
        "os", "deal", "deal.pre", "pkg.sub.sibling", "pkg.cousin", "pkg.pkg.mod.thing", "arch.model.codec", "json",
    ])


def test_relative_imports_from_a_package():
    f = facts("from . import a\nfrom .b import c\n", path="src/pkg/__init__.py", unit="pkg")
    assert sorted(i.target for i in f.imports) == ["pkg.a", "pkg.b.c"]


@realizes("arch.realize.python.extract#AC1")
def test_public_api_respects_dunder_all_and_underscores():
    names = {s.name: s for s in facts().symbols}
    assert set(names) == {"api", "Port", "Port.run"}
    assert names["api"].signature == "api(x: int) -> int"
    assert names["Port"].signature == "class Port(Base)"
    assert {s.name for s in facts("def f(): ...\ndef _g(): ...\nX = 1\n").symbols} == {"f", "X"}


@realizes("arch.realize.python.extract#AC5")
def test_deal_contracts_are_read_syntactically():
    got = {(c.symbol, c.kind) for c in facts().contracts}
    assert got == {("Port.run", "has"), ("Port.run", "ensure"), ("checked", "pre")}


@realizes("arch.realize.facts#AC1")
def test_design_links_carry_locations():
    links = facts().links
    assert [(l.symbol, l.target) for l in links] == [("checked", "a.b#AC1"), ("checked", "a.c")]
    assert all(l.location.path == "src/pkg/sub/mod.py" and l.location.line > 1 for l in links)


@realizes("arch.realize.python#AC2", "arch.realize.facts#AC5")
def test_syntax_errors_become_facts_and_claim_nothing():
    f = facts("def broken(:\n")
    assert len(f.errors) == 1 and f.errors[0].location.line == 1
    assert f.units[0].capabilities == frozenset()
    assert Capability.EFFECTS not in facts().units[0].capabilities  # not analyzed yet, so not claimed


@realizes("arch.realize#AC1", "arch.realize.python#AC1")
@given(st.text())
def test_extraction_never_raises_and_is_deterministic(text):
    assert facts(text) == facts(text)
