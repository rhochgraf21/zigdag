from __future__ import annotations

from arch import realizes
from arch.check import check
from arch.check.engine import Severity
from arch.integrate.agent.render import core_skill
from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import DesignPath
from arch.realize.facts import NameKind, Role, SourcePath, UnitName, needs_description
from arch.realize.python.extract import extract, names
from tests.conftest import NEED, component

SRC = '''from typing import NewType

SourcePath = NewType("SourcePath", str)
CONFIG_FILE = "arch.toml"


class Operation:
    def apply_to(self, draft: int) -> None:
        """Make this edit in the draft."""


class Link(Operation):
    def apply_to(self, draft: int) -> None:
        pass


class Edit:
    """One file edit."""

    path: SourcePath
    suffixes: tuple[FileSuffix, ...]
    before: str  # the before
    after: str  # the text once the edit is applied
    target: SourcePath


def total(edits: Edit) -> int:
    count = len(edits)
    for edit in edits:
        count += len(edit)
    return count
'''


def facts():
    return extract(SourcePath("src/m.py"), SRC, UnitName("m"), Role.SOURCE)


@realizes("arch.realize.facts#AC10", "arch.realize.python.extract#AC11")
def test_only_names_their_type_does_not_explain_need_a_description():
    need = {name for _, name in needs_description(facts())}
    assert need == {"SourcePath", "Operation", "Link", "Edit.target", "total"}  # a class always needs one
    # path: SourcePath and suffixes: tuple[FileSuffix, ...] say it; Link.apply_to shares Operation.apply_to's
    # description; Edit.before has one (a poor one, see below); CONFIG_FILE shows its value
    symbols = {s.name: s for s in facts().symbols}
    assert symbols["CONFIG_FILE"].kind == "constant" and symbols["CONFIG_FILE"].signature == "CONFIG_FILE = 'arch.toml'"


@realizes("arch.check.conformance#AC14", "arch.check.conformance#AC15")
def test_conformance_reports_missing_and_empty_descriptions_more_strictly_as_code_matures():
    def found(status):
        design = codec.load({DesignPath("needs/n.md"): NEED, DesignPath("components/m.md"): component(serves="n", status=status)})
        return {(f.rule, f.key, f.severity) for f in check(Graph(design), facts()).findings if f.rule in ("C014", "C015")}

    specified = found("specified")
    assert ("C014", "undescribed:m.Edit.target", Severity.INFO) in specified
    assert ("C015", "restated:m.Edit.before", Severity.INFO) in specified
    assert not any(k.endswith((".path", ".after", ".suffixes", "Link.apply_to", "CONFIG_FILE")) for _, k, _ in specified)
    assert {s for _, _, s in found("contracted")} == {Severity.WARNING}
    assert {s for _, _, s in found("verified")} == {Severity.ERROR}


@realizes("arch.realize.python.extract#AC10")
def test_a_local_resolves_to_the_line_that_set_it():
    refs = {(r.text, r.location.line, r.bound_at, r.binding, r.target)
            for r in names(SourcePath("src/m.py"), SRC, UnitName("m")) if r.kind is NameKind.LOCAL}
    assert refs == {("edit", 30, 29, "for edit in edits:", ""),  # a loop: its header line, without the body
                    ("count", 31, 28, "count = len(edits)", "")}  # len is a builtin: nothing to point at


@realizes("arch.integrate.agent#AC8")
def test_the_core_skill_asks_for_descriptions_of_interface_names_only():
    skill = core_skill()
    assert "Describe the interface names you add or change" in skill and "Do not comment local variables" in skill
