from __future__ import annotations

import pytest

from arch import realizes
from arch.check import check
from arch.check.engine import Severity
from arch.guide.method import METHODS, AbstractOp, MethodName
from arch.model import codec
from arch.model.graph import Graph


@realizes("arch.guide.method#AC1")
def test_every_method_states_inputs_steps_exit_criteria_and_operations():
    assert {m.name for m in METHODS} == set(MethodName)
    for m in METHODS:
        assert m.inputs and m.steps and m.exit_criteria and m.operations, m.name


@realizes("arch.guide.method#AC2", "arch.guide#AC2")
def test_every_method_ends_with_the_deterministic_check():
    for m in METHODS:
        assert AbstractOp.CHECK in m.self_check[-1].uses, m.name


@realizes("arch.guide.method#AC3")
@pytest.mark.parametrize("m", METHODS, ids=lambda m: m.name.value)
def test_worked_examples_pass_the_check(m):
    report = check(Graph(codec.load(m.example.result)))
    assert [f for f in report.findings if f.severity is not Severity.INFO] == [], m.name
