"""Evaluate rules over a design, producing findings with stable identities.

Realizes arch.check.engine. A finding's identity is (rule, subject, key) and never includes line numbers, so
responses survive unrelated edits. Severity is not chosen by rules: it follows from the station where the
defect is made, the kind of finding, who noticed it, and how far the subject has come (see `severity_of`).
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import NewType, TypeAlias

from arch.model.graph import Graph
from arch.model.ids import ComponentId, Location, Text
from arch.model.schema import Status
from arch.realize.facts import Facts, SourceLocation

RuleId = NewType("RuleId", str)  # the detector: a rule id such as S104, or a critic question, a person or an agent
Subject = NewType("Subject", str)  # a node id, or a design path for file-level problems
FindingKey = NewType("FindingKey", str)  # tells two findings of one detector on one subject apart
FindingIdentity: TypeAlias = tuple[RuleId, Subject, FindingKey]


class Severity(enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def blocks(self) -> bool:
        return self is Severity.ERROR


class Station(enum.Enum):
    """Where in the work a defect is made, and so where it should be caught. In the order work flows."""

    FORM = "form"  # the design files parse, and their references resolve
    NEEDS = "needs"  # what stakeholders need, and what serves each need
    REQUIREMENTS = "requirements"  # what each part must do, and the criteria that pin it down
    SOLUTION = "solution"  # how each part does it: its secret, its children, its uses, its decisions
    INTERFACE = "interface"  # what a part offers others: code that exists, typed and described, with criteria linked
    CODE = "code"  # the code as written, against the design and its constraints
    EVIDENCE = "evidence"  # tests and contracts that show the criteria hold
    REVIEW = "review"  # a person's judgement of a change

    def precedes(self, other: Station) -> bool:
        """Whether work reaches this station before `other`."""
        stations = list(Station)
        return stations.index(self) < stations.index(other)


# what each status claims is done. Form, code and review are always in force: a design that exists must
# parse, code that exists must keep the constraints, and what a review found must be answered.
_ALWAYS = frozenset({Station.FORM, Station.CODE, Station.REVIEW})
PASSED: dict[Status, frozenset[Station]] = {
    Status.DRAFT: _ALWAYS,
    Status.SPECIFIED: _ALWAYS | {Station.NEEDS, Station.REQUIREMENTS, Station.SOLUTION},
    Status.CONTRACTED: _ALWAYS | {Station.NEEDS, Station.REQUIREMENTS, Station.SOLUTION, Station.INTERFACE},
    Status.VERIFIED: frozenset(Station),
}


class Kind(enum.Enum):
    DEFECT = "defect"  # something is wrong
    QUESTION = "question"  # something may be wrong; a person must judge, or a detector could not tell
    IDEA = "idea"  # something could be better


class Source(enum.Enum):
    """Who noticed it. Only rules are deterministic, so only rules can fail a check on their own."""

    RULE = "rule"
    CRITIC = "critic"  # a model reviewing design text with a rubric
    PERSON = "person"
    AGENT = "agent"


@dataclass(frozen=True)
class Finding:
    subject: Subject
    rule: RuleId
    key: FindingKey
    kind: Kind
    message: Text
    hint: Text
    location: Location | SourceLocation | None = None
    station: Station = Station.FORM  # where the defect was made; a rule's findings take the rule's station
    severity: Severity = Severity.INFO  # set by the engine; see severity_of
    source: Source = Source.RULE
    evidence: Text | None = None  # the words the finding is about, quoted exactly
    found_at: Station | None = None  # where it was noticed, when that is later than where it was made

    @property
    def identity(self) -> FindingIdentity:
        return (self.rule, self.subject, self.key)

    @property
    def escaped(self) -> bool:
        """Noticed at a later station than the one that made it: a detector upstream missed it."""
        return self.found_at is not None and self.station.precedes(self.found_at)


FindingRef = NewType("FindingRef", str)  # RULE@SUBJECT#KEY: how a person or an agent names a finding


def ref_of(identity: FindingIdentity) -> FindingRef:
    rule, subject, key = identity
    return FindingRef(f"{rule}@{subject}#{key}")


def parse_ref(ref: FindingRef) -> FindingIdentity:
    """The identity a reference names. Subjects never contain '@' or '#'; keys may."""
    rule, at, rest = ref.partition("@")
    subject, hash_, key = rest.partition("#")
    if not (at and hash_ and rule and subject and key):
        raise ValueError(f"'{ref}' is not a finding reference (RULE@SUBJECT#KEY, as `arch findings` lists them)")
    return (RuleId(rule), Subject(subject), FindingKey(key))


def severity_of(finding: Finding, graph: Graph) -> Severity:
    """One rule for every finding. A defect at a station its subject has passed is an error, when a rule
    found it: the line stops. Anything else at a passed station is a warning. Findings about stations the
    subject has not reached yet, and ideas, are information."""
    if finding.kind is Kind.IDEA:
        return Severity.INFO
    cid = ComponentId(finding.subject)
    passed = PASSED[graph[cid].status] if cid in graph else frozenset(Station)  # needs, constraints, files
    if finding.station not in passed:
        return Severity.INFO
    if finding.kind is Kind.DEFECT and finding.source is Source.RULE:
        return Severity.ERROR
    return Severity.WARNING


@dataclass(frozen=True, eq=False)  # identity-hashed, so rules can cache what they derive from it
class Context:
    graph: Graph
    facts: Facts | None = None  # None: check the design alone


@dataclass(frozen=True)
class Rule:
    id: RuleId
    station: Station
    summary: Text
    evaluate: Callable[[Context], Iterable[Finding]]


@dataclass(frozen=True)
class Report:
    findings: tuple[Finding, ...]
    answered: frozenset[FindingIdentity] = frozenset()  # findings with a response; reported but never blocking

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity.blocks and f.identity not in self.answered)

    def is_answered(self, finding: Finding) -> bool:
        return finding.identity in self.answered


def run(rules: Iterable[Rule], context: Context) -> Report:
    findings: set[Finding] = set()
    for rule in rules:
        try:
            for f in rule.evaluate(context):
                placed = replace(f, station=rule.station)  # a rule's findings are made where the rule looks
                findings.add(replace(placed, severity=severity_of(placed, context.graph)))
        except Exception as e:  # a broken rule must not hide the others' findings
            findings.add(
                Finding(
                    Subject("arch"), RuleId("E000"), FindingKey(rule.id), Kind.DEFECT,
                    Text(f"rule {rule.id} failed: {type(e).__name__}: {e}"), Text("this is a bug in arch"),
                    severity=Severity.ERROR,
                )
            )
    return Report(tuple(sorted(findings, key=lambda f: (f.subject, f.rule, f.key))))
