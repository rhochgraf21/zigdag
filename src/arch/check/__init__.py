"""Decide whether the design is well formed and the realization conforms (arch.check)."""

from __future__ import annotations

from arch.check import conformance, structure
from arch.check.engine import Context, Report, run
from arch.model.graph import Graph
from arch.realize.facts import Facts


def check(graph: Graph, facts: Facts | None = None) -> Report:
    """Structure rules always; conformance rules when facts about the code are given.
    Statement rules and the baseline arrive later."""
    rules = structure.RULES + (conformance.RULES if facts is not None else ())
    return run(rules, Context(graph, facts))


__all__ = ["check"]
