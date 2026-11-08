"""The record as written (DESIGN2 §7): what each domain file says, as values with the place they are written."""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from zigdag.core.findings import Span
from zigdag.core.names import CheckKindName, CodeName, FrName, OutcomeRef, RuleId, Slug, StatementRef

T = TypeVar("T")


@dataclass(frozen=True)
class At(Generic[T]):
    """A value and where it is written."""

    value: T
    span: Span


@dataclass(frozen=True)
class Sentence:
    text: str
    span: Span


@dataclass(frozen=True)
class Outcome:
    ref: OutcomeRef
    sentence: Sentence


@dataclass(frozen=True)
class Job:
    name: Slug
    job: Sentence
    performer: Sentence
    outcomes: tuple[Outcome, ...]
    built_in: bool = False


@dataclass(frozen=True)
class Statement:
    ref: StatementRef
    sentence: Sentence


@dataclass(frozen=True)
class Fr:
    name: FrName
    serves: tuple[At[OutcomeRef], ...]
    serves_span: Span | None  # where `serves` is written, when it is
    statements: tuple[Statement, ...]
    span: Span


ParamValue = str | tuple[str, ...]  # parameters are text until a check kind's schema converts them


@dataclass(frozen=True)
class Excepted:
    code: CodeName
    reason: str | None
    span: Span


@dataclass(frozen=True)
class CheckUse:
    kind: At[CheckKindName]
    params: Mapping[str, At[ParamValue]]
    excepted: tuple[Excepted, ...]


@dataclass(frozen=True)
class Constraint:
    name: RuleId
    on: At[FrName]
    serves: tuple[At[OutcomeRef], ...]
    check: CheckUse | None
    statement: Sentence | None
    reason: str | None
    span: Span


class EvidenceKind(enum.Enum):
    UNIT_TEST = "unit-test"
    PROPERTY_TEST = "property-test"
    CONTRACT = "contract"
    BENCHMARK = "benchmark"
    TEST_REPORT = "test-report"


class Gate(enum.Enum):
    CRITIQUE_BEFORE_REVIEW = "critique-before-review"
    PERSON_APPROVES_DESIGN = "person-approves-design"
    STOP_ON_ERROR = "stop-on-error"
    COUNTERMEASURE_ON_ESCAPE = "countermeasure-on-escape"


@dataclass(frozen=True)
class CodeRule:
    check: CheckUse


@dataclass(frozen=True)
class Verification:
    evidence: EvidenceKind
    report: str | None


@dataclass(frozen=True)
class Validation:
    measures: At[OutcomeRef]
    report: str


@dataclass(frozen=True)
class Build:
    step: str
    produces: tuple[str, ...]


@dataclass(frozen=True)
class Workflow:
    gate: Gate


ProcessKind = CodeRule | Verification | Validation | Build | Workflow


@dataclass(frozen=True)
class ProcessVariable:
    name: RuleId
    on: At[FrName]
    serves: tuple[At[OutcomeRef], ...]
    kind: ProcessKind
    reason: str | None
    span: Span


class Domain(enum.Enum):
    CUSTOMER = "customer"
    FUNCTIONAL = "functional"
    PHYSICAL = "physical"
    PROCESS = "process"


@dataclass(frozen=True)
class Tuning:
    """An entry that tunes a built-in rule (DESIGN2 §4.4): it may only change parameters, except, scope or switch it off."""

    name: RuleId
    params: Mapping[str, At[ParamValue]]
    excepted: tuple[Excepted, ...]
    on: At[FrName] | None
    off: bool
    reason: str | None
    span: Span


@dataclass(frozen=True)
class Placement:
    """A physical.yaml entry: the units a DP maps to, when its name does not point at them."""

    dp: FrName
    units: tuple[At[CodeName], ...]
    span: Span


@dataclass(frozen=True)
class Record:
    jobs: tuple[Job, ...]
    frs: Mapping[FrName, Fr]
    constraints: Mapping[RuleId, Constraint]
    process: Mapping[RuleId, ProcessVariable]
    tunings: Mapping[RuleId, Tuning]
    placements: Mapping[FrName, Placement]

    @property
    def outcomes(self) -> Mapping[OutcomeRef, Outcome]:
        return {o.ref: o for job in self.jobs for o in job.outcomes}

    @property
    def root(self) -> Fr | None:
        roots = [fr for name, fr in self.frs.items() if "." not in name]
        return roots[0] if len(roots) == 1 else None
