"""The most valuable next design actions, ranked.

Realizes arch.guide.next. Turns findings and gaps into actions, each saying what to do and which method
or operation applies. Blocking problems come first, then whatever stands between a need and verified
code, nearest the needs first. Deterministic: ties are broken by subject.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import NewType

from arch.check.engine import Finding, Report, Severity
from arch.guide.method import AbstractOp, MethodName
from arch.model.graph import Graph
from arch.model.ids import ComponentId, Text, is_within


class ActionKind(enum.Enum):
    """In priority order."""

    FIX_BLOCKING = "fix a blocking problem"
    RESOLVE_COUPLING = "resolve coupling"
    TRACE_TO_NEEDS = "trace work to needs"
    STATE_REQUIREMENTS = "state requirements and criteria"
    STATE_SECRET = "state what a component hides"
    BUILD = "build a component that has no code yet"
    LINK_EVIDENCE = "link criteria to tests"
    IMPROVE = "address a warning"


_GUIDANCE: dict[str, tuple[ActionKind, MethodName | None, AbstractOp | None]] = {
    "S005": (ActionKind.RESOLVE_COUPLING, MethodName.RESOLVE_COUPLING, None),
    "S002": (ActionKind.TRACE_TO_NEEDS, MethodName.ELICIT_NEEDS, AbstractOp.LINK),
    "S003": (ActionKind.TRACE_TO_NEEDS, MethodName.ELICIT_NEEDS, AbstractOp.LINK),
    "S009": (ActionKind.STATE_REQUIREMENTS, MethodName.WRITE_REQUIREMENTS, AbstractOp.ADD_CRITERION),
    "S006": (ActionKind.STATE_SECRET, MethodName.DECOMPOSE, AbstractOp.SET_FIELD),
    "C005": (ActionKind.LINK_EVIDENCE, None, AbstractOp.CONTEXT),
    "C003": (ActionKind.BUILD, None, AbstractOp.CONTEXT),
}
ActionLimit = NewType("ActionLimit", int)
_STATEMENT_RULES_PREFIX = "S1"  # statement-quality rules (arch.check.statements)


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    subject: Text
    what: Text
    method: MethodName | None
    operation: AbstractOp | None
    because: Finding


def next_actions(graph: Graph, report: Report, scope: ComponentId | None = None,
                 limit: ActionLimit = ActionLimit(10)) -> tuple[Action, ...]:
    actions = [a for f in report.findings if (a := _action(f, report)) is not None and _in_scope(graph, a, scope)]
    actions.sort(key=lambda a: (list(ActionKind).index(a.kind), _depth(graph, a.subject), a.subject, a.because.rule))
    return tuple(actions[:limit])


def _action(f: Finding, report: Report) -> Action | None:
    if report.is_baselined(f):
        return None
    guidance = _GUIDANCE.get(f.rule)
    about_statements = f.rule.startswith(_STATEMENT_RULES_PREFIX)
    if f.severity is Severity.ERROR:
        coupling = guidance is not None and guidance[0] is ActionKind.RESOLVE_COUPLING
        kind = ActionKind.RESOLVE_COUPLING if coupling else ActionKind.FIX_BLOCKING
        method = guidance[1] if guidance else (MethodName.WRITE_REQUIREMENTS if about_statements else None)
        op = guidance[2] if guidance else None
    elif guidance is not None:
        kind, method, op = guidance
    elif f.severity is Severity.WARNING:
        kind, method, op = ActionKind.IMPROVE, MethodName.WRITE_REQUIREMENTS if about_statements else None, None
    else:
        return None
    return Action(kind, Text(f.subject), Text(f"{f.message}: {f.hint}"), method, op, f)


def _in_scope(graph: Graph, action: Action, scope: ComponentId | None) -> bool:
    if scope is None:
        return True
    subject = ComponentId(action.subject)
    return subject in graph and is_within(subject, scope)


def _depth(graph: Graph, subject: Text) -> int:
    return subject.count(".") if subject in graph else 99


__all__ = ["Action", "ActionKind", "ActionLimit", "next_actions"]
