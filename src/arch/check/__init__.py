"""Decide whether the design is well formed and the realization conforms (arch.check)."""

from __future__ import annotations

from arch.check import conformance, critique, statements, structure
from arch.check.engine import Context, Finding, FindingKey, Kind, Report, RuleId, Severity, Source, Station, Subject, run
from arch.check.ledger import Answer, Ledger, Response
from arch.check.statements import Lexicon, Term
from arch.model.graph import Graph
from arch.realize.facts import Facts


def check(graph: Graph, facts: Facts | None = None, ledger: Ledger = Ledger(), lexicon: Lexicon = Lexicon()) -> Report:
    """Structure and statement rules always; conformance rules when facts about the code are given. Then what
    critics, people and agents noticed, from the ledger, with every answer given so far."""
    rules = structure.RULES + statements.rules(lexicon) + critique.RULES + (conformance.RULES if facts is not None else ())
    return ledger.apply(run(rules, Context(graph, facts)), graph)


__all__ = ["Answer", "Context", "Finding", "FindingKey", "Kind", "Ledger", "Lexicon", "Report", "Response", "RuleId",
           "Severity", "Source", "Station", "Subject", "Term", "check"]
