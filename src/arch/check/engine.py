"""Evaluate rules over a design, producing findings with stable identities.

Realizes arch.check.engine. A finding's identity is (rule, subject, key) and never includes line
numbers, so baselines survive unrelated edits.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import NewType, TypeAlias

from arch.model.graph import Graph
from arch.model.ids import Location, Text
from arch.model.schema import Status
from arch.realize.facts import Facts, SourceLocation

RuleId = NewType("RuleId", str)
Subject = NewType("Subject", str)  # a node id, or a design path for file-level problems
FindingKey = NewType("FindingKey", str)
FindingIdentity: TypeAlias = tuple[RuleId, Subject, FindingKey]


class Severity(enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def blocks(self) -> bool:
        return self is Severity.ERROR


@dataclass(frozen=True)
class Finding:
    subject: Subject
    rule: RuleId
    key: FindingKey
    severity: Severity
    message: Text
    hint: Text
    location: Location | SourceLocation | None = None

    @property
    def identity(self) -> FindingIdentity:
        return (self.rule, self.subject, self.key)


@dataclass(frozen=True, eq=False)  # identity-hashed, so rules can cache what they derive from it
class Context:
    graph: Graph
    facts: Facts | None = None  # None: check the design alone


@dataclass(frozen=True)
class Rule:
    id: RuleId
    summary: Text
    evaluate: Callable[[Context], Iterable[Finding]]


@dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...]
    baselined: frozenset[FindingIdentity] = frozenset()  # existed before; reported but never blocking

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity.blocks and f.identity not in self.baselined)

    def is_baselined(self, finding: Finding) -> bool:
        return finding.identity in self.baselined


def by_maturity(status: Status, *, draft: Severity, specified: Severity, contracted: Severity) -> Severity:
    """Severity that tightens as a component matures (see arch and arch.check decisions)."""
    if status is Status.DRAFT:
        return draft
    return specified if status is Status.SPECIFIED else contracted


def run(rules: Iterable[Rule], context: Context) -> Report:
    findings: set[Finding] = set()
    for rule in rules:
        try:
            findings.update(rule.evaluate(context))
        except Exception as e:  # a broken rule must not hide the others' findings
            findings.add(
                Finding(
                    Subject("arch"), RuleId("E000"), FindingKey(rule.id), Severity.ERROR,
                    Text(f"rule {rule.id} failed: {type(e).__name__}: {e}"), Text("this is a bug in arch"),
                )
            )
    return Report(tuple(sorted(findings, key=lambda f: (f.subject, f.rule, f.key))))
