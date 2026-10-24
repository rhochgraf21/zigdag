"""arch's own design, checked by arch (arch#AC5)."""

from __future__ import annotations

from pathlib import Path

from arch import realizes
from arch.check import check
from arch.check.engine import Severity
from arch.guide.plan import plan
from arch.integrate.cli import main
from arch.integrate.workspace import find
from arch.model.graph import Graph
from arch.model.matrix import Coupling, matrix_of

WS = find(Path(__file__).parent)
GRAPH = Graph(WS.design())


@realizes("arch#AC5")
def test_own_design_has_no_findings():
    assert check(GRAPH).findings == ()


@realizes("arch#AC2")
def test_own_code_conforms_to_own_design():
    report = check(GRAPH, WS.facts())
    assert [f for f in report.findings if f.severity is not Severity.INFO] == []


@realizes("arch.model.matrix#AC1")
def test_own_matrices_are_not_coupled():
    g = GRAPH
    assert all(matrix_of(g, c).coupling is not Coupling.COUPLED for c in g.ids() if g.children(c))


@realizes("arch.guide.plan#AC1")
def test_design_rules_come_first():
    first = plan(GRAPH).layering.layers[0]
    assert {"arch.model.schema", "arch.realize.facts"} <= set(first)


@realizes("arch.integrate.cli#AC1")
def test_cli_exit_codes(capsys):
    assert main(["--project", str(WS.root), "check"]) == 0
    assert main(["--project", str(WS.root), "outline", "no.such.thing"]) == 2
