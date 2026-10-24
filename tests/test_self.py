"""arch's own design, checked by arch (arch#AC5)."""

from __future__ import annotations

from pathlib import Path

from arch import realizes
from arch.check import check
from arch.guide.plan import plan
from arch.integrate.cli import main
from arch.integrate.workspace import find
from arch.model.matrix import Coupling, matrix_of

WS = find(Path(__file__).parent)


@realizes("arch#AC5")
def test_own_design_has_no_findings():
    assert check(WS.graph()).findings == ()


@realizes("arch.model.matrix#AC1")
def test_own_matrices_are_not_coupled():
    g = WS.graph()
    assert all(matrix_of(g, c).coupling is not Coupling.COUPLED for c in g.ids() if g.children(c))


@realizes("arch.guide.plan#AC1")
def test_design_rules_come_first():
    first = plan(WS.graph()).layering.layers[0]
    assert {"arch.model.schema", "arch.realize.facts"} <= set(first)


@realizes("arch.integrate.cli#AC1")
def test_cli_exit_codes(capsys):
    assert main(["--project", str(WS.root), "check"]) == 0
    assert main(["--project", str(WS.root), "outline", "no.such.thing"]) == 2
