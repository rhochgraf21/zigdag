"""Decide whether the design is well formed and the realization conforms (arch.check)."""

from __future__ import annotations

from arch.check import conformance, statements, structure
from arch.check.baseline import Baseline, BaselineText, applied
from arch.check.engine import Context, Finding, FindingKey, Report, RuleId, Severity, Subject, run
from arch.check.statements import Lexicon, Term
from arch.model.graph import Graph
from arch.model.ids import Text
from arch.realize.facts import Facts


def check(graph: Graph, facts: Facts | None = None, baseline: Baseline = Baseline(),
          lexicon: Lexicon = Lexicon()) -> Report:
    """Structure and statement rules always; conformance rules when facts about the code are given.
    Suppressed findings are dropped; baselined ones are reported but never block."""
    rules = structure.RULES + statements.rules(lexicon) + (conformance.RULES if facts is not None else ())
    return applied(_suppressed(run(rules, Context(graph, facts)), graph), baseline)


def _suppressed(report: Report, graph: Graph) -> Report:
    """Drop findings a node suppresses with a reason; report reasonless and unused suppressions."""
    design = graph.design
    nodes = {**{k: v.suppressions for k, v in design.components.items()},
             **{k: v.suppressions for k, v in design.needs.items()}}
    locations = {**{k: v.location for k, v in design.components.items()}, **{k: v.location for k, v in design.needs.items()}}
    kept: list[Finding] = []
    used: set[tuple[str, str]] = set()
    for f in report.findings:
        match = next((s for s in nodes.get(f.subject, ()) if s.rule == f.rule and s.reason), None)
        if match is None:
            kept.append(f)
        else:
            used.add((f.subject, f.rule))
    for node, suppressions in sorted(nodes.items()):
        for s in suppressions:
            if s.reason is None:
                kept.append(Finding(Subject(node), RuleId("S105"), FindingKey(f"suppress:{s.rule}"), Severity.WARNING,
                                    Text(f"suppresses {s.rule} without a reason"),
                                    Text("give the reason: `suppress: {RULE: why this is acceptable here}`"), locations[node]))
            elif (node, s.rule) not in used:
                kept.append(Finding(Subject(node), RuleId("S106"), FindingKey(f"unused:{s.rule}"), Severity.INFO,
                                    Text(f"suppresses {s.rule}, which no longer occurs here"),
                                    Text("remove the suppression"), locations[node]))
    return Report(tuple(kept), report.baselined)


__all__ = ["Baseline", "BaselineText", "Lexicon", "Term", "check"]
