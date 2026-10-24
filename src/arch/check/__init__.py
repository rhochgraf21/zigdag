"""Decide whether the design is well formed and the realization conforms (arch.check)."""

from __future__ import annotations

from arch.check import structure
from arch.check.engine import Context, Report, run
from arch.model.graph import Graph


def check(graph: Graph) -> Report:
    """Run every rule set that exists so far. Statements, conformance and baseline arrive later."""
    return run(structure.RULES, Context(graph))


__all__ = ["check"]
