"""Decide whether the design is well formed and the realization conforms (arch.check)."""

from __future__ import annotations

from arch.check import conformance, structure
from arch.check.baseline import Baseline, BaselineText, applied
from arch.check.engine import Context, Report, run
from arch.model.graph import Graph
from arch.realize.facts import Facts


def check(graph: Graph, facts: Facts | None = None, baseline: Baseline = Baseline()) -> Report:
    """Structure rules always; conformance rules when facts about the code are given. Findings in the
    baseline are reported but never block."""
    rules = structure.RULES + (conformance.RULES if facts is not None else ())
    return applied(run(rules, Context(graph, facts)), baseline)


__all__ = ["Baseline", "BaselineText", "check"]
