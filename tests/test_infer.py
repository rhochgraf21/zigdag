from __future__ import annotations

from arch import realize, realizes
from arch.change import Outcome, apply
from arch.check import check
from arch.check.engine import Severity
from arch.guide.infer import infer
from arch.integrate.cli import main
from arch.model import codec
from arch.model.graph import Graph
from arch.model.schema import Status
from arch.realize.facts import Roots, Snapshot, SourcePath

CODE = {
    "src/app/__init__.py": '"""The app."""\n',
    "src/app/core/__init__.py": '"""Business rules."""\nfrom app.core.rules import price\n',
    "src/app/core/rules.py": '"""Compute prices from rules."""\ndef price(x): return x\n',
    "src/app/core/store.py": "from app.core import rules\n",
    "src/app/web/__init__.py": "",
    "src/app/web/views.py": "from app.core.rules import price\nfrom app.web import forms\n",
    "src/app/web/forms.py": "from app.web import views\n",
}


def inferred():
    snap = Snapshot({SourcePath(k): v for k, v in CODE.items()}, Roots(("src",), ()))
    facts = realize.extract(snap)
    inference = infer(facts)
    result = apply(codec.load({}), inference.operations, snap, facts.links)
    return inference, result, facts


@realizes("arch.guide.infer#AC1", "arch.guide.infer#AC4")
def test_one_draft_component_per_unit_with_docstring_summaries():
    inference, result, _ = inferred()
    assert result.outcome is Outcome.APPLIED, result.reason
    comps = result.after.components
    assert set(comps) == {"app", "app.core", "app.core.rules", "app.core.store", "app.web", "app.web.views", "app.web.forms"}
    assert all(c.status is Status.DRAFT for c in comps.values())
    assert comps["app.core.rules"].realizes == "Compute prices from rules."


@realizes("arch.guide.infer#AC2")
def test_inferred_uses_and_exports_leave_no_boundary_errors():
    _, result, facts = inferred()
    comps = result.after.components
    assert comps["app.web.views"].uses == ("core.rules", "forms")
    assert comps["app.web"].uses == ("core",) and comps["app.core"].exports == ("rules",)
    report = check(Graph(result.after), facts)
    assert not [f for f in report.findings if f.rule in ("C001", "S007", "S008") and f.severity is Severity.ERROR]


@realizes("arch.guide.infer#AC3")
def test_import_cycles_are_recorded_and_block_only_a_specified_parent():
    inference, result, facts = inferred()
    assert inference.cycles == (("app.web.forms", "app.web.views"),)
    web = result.after.components["app.web"]
    assert [d.title for d in web.decisions] == ["Inferred import cycle among forms, views"]
    s005 = [f for f in check(Graph(result.after), facts).findings if f.rule == "S005"]
    assert [f.severity for f in s005] == [Severity.INFO]  # a draft has not claimed its solution yet


@realizes("arch.guide.infer#AC5")
def test_init_writes_a_design_that_passes_its_first_check(tmp_path, capsys):
    for path, text in {**CODE, "tests/test_x.py": "@realizes('app.core#AC1')\ndef test(): ...\n"}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    assert main(["--project", str(tmp_path), "init"]) == 0
    assert (tmp_path / "design/components/app/core/rules.md").is_file()
    assert (tmp_path / "design/responses/baseline.md").read_text().count("C004") == 1  # links a criterion not yet written
    assert main(["--project", str(tmp_path), "check"]) == 0
    assert main(["--project", str(tmp_path), "init"]) == 2  # refuses to overwrite a design
