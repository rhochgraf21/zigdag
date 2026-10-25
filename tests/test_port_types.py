from __future__ import annotations

from arch import realize, realizes
from arch.check import check
from arch.realize.facts import Role, Roots, Snapshot, SourcePath, UnitName
from arch.realize.python.extract import extract
from tests.conftest import NEED, component, graph


def symbols(src):
    return {s.name: s for s in extract(SourcePath("src/m.py"), src, UnitName("m"), Role.SOURCE).symbols}


@realizes("arch.realize.python.extract#AC7")
def test_type_leaves_ignore_containers_and_literals():
    s = symbols(
        "from typing import Literal\n"
        "def f(a: list[str], b: tuple[Id, ...], c: Mapping[Id, 'Node'] | None, d: Literal['x'], e: typing.Any) -> Callable[..., R]: ...\n"
    )["f"]
    leaves = {p.name: p.type.leaves for p in s.parameters}
    assert leaves == {"a": {"str"}, "b": {"Id"}, "c": {"Id", "Node", "None"}, "d": set(), "e": {"Any"}}
    assert s.returns.leaves == {"R"}


def test_fields_and_methods_are_part_of_the_port():
    s = symbols("class C:\n    size: int\n    _hidden: str\n    def m(self, flag: bool) -> bool: ...\n")
    assert s["C.size"].kind == "field" and s["C.size"].returns.leaves == {"int"}
    assert "C._hidden" not in s
    assert [p.name for p in s["C.m"].parameters] == ["flag"]  # self is not part of the port


TYPED = "---\nkind: constraint\napplies_to: [s]\nrule:\n  port_types:\n    forbid: [str, int, bool]\n    allow_in_returns: [bool]\n    except_in: [s.cli]\n---\nTyped.\n"


@realizes("arch.check.conformance#AC10")
def test_rule_flags_bare_builtins_in_ports_but_not_predicates_or_exempt_parts():
    design = graph({"needs/n.md": NEED, "constraints/t.md": TYPED, "components/s.md": component(serves="n"),
                    "components/s/core.md": component(serves="n"), "components/s/cli.md": component(serves="n")})
    code = {"src/s/__init__.py": "",
            "src/s/core.py": ("Name = NewType('Name', str)\n"
                              "def ok(n: Name) -> bool: ...\n"
                              "def bad(n: str, verbose: bool) -> int: ...\n"
                              "def untyped(n): ...\n"
                              "def _private(n: str): ...\n"),
            "src/s/cli.py": "def main(argv: list[str]) -> int: ...\n"}
    facts = realize.extract(Snapshot({SourcePath(k): v for k, v in code.items()}, Roots(("src",), ())))
    report = check(design, facts)
    found = {(f.key, report.severity(f).value) for f in report.findings if f.rule == "C011"}
    assert found == {("bare:s.core.bad:n", "error"), ("bare:s.core.bad:verbose", "error"),
                     ("bare:s.core.bad:return", "error"), ("untyped:s.core.untyped:n", "warning")}
