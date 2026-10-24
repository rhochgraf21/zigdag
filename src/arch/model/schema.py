"""Node kinds, their fields, and what makes a single node valid.

Realizes arch.model.schema. Hides field representation and per-field validation.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NewType

ComponentId = NewType("ComponentId", str)
NeedId = NewType("NeedId", str)
ConstraintId = NewType("ConstraintId", str)
DecisionId = NewType("DecisionId", str)
CriterionId = NewType("CriterionId", str)  # "<component id>#ACn"
Ref = NewType("Ref", str)  # a reference as written; arch.model.graph resolves it
Text = NewType("Text", str)
FieldName = NewType("FieldName", str)
DesignPath = NewType("DesignPath", str)  # '/'-separated, relative to the design root
LineNo = NewType("LineNo", int)
PolicyJson = NewType("PolicyJson", str)  # canonical JSON of a constraint's rule, until rules are typed


class Kind(enum.Enum):
    NEED = "need"
    COMPONENT = "component"
    CONSTRAINT = "constraint"
    DECISION = "decision"


class Status(enum.Enum):
    """Component maturity. Checks tighten as a component moves down this list."""

    DRAFT = "draft"
    SPECIFIED = "specified"
    CONTRACTED = "contracted"
    VERIFIED = "verified"

    @property
    def rank(self) -> int:
        return list(Status).index(self)


class DecisionVariant(enum.Enum):
    DECISION = "decision"
    CONTRADICTION = "contradiction"


class DecisionStatus(enum.Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, order=True)
class Location:
    path: DesignPath
    line: LineNo = LineNo(1)

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Criterion:
    id: CriterionId
    text: Text
    location: Location


@dataclass(frozen=True)
class Component:
    id: ComponentId
    realizes: Text
    solution: Text
    hides: Text | None
    serves: tuple[NeedId, ...]
    uses: tuple[Ref, ...]
    exports: tuple[Ref, ...]
    status: Status
    criteria: tuple[Criterion, ...]
    location: Location


@dataclass(frozen=True)
class Need:
    id: NeedId
    statement: Text
    stakeholder: Text | None
    signal: Text | None
    location: Location


@dataclass(frozen=True)
class Constraint:
    id: ConstraintId
    applies_to: tuple[Ref, ...]  # absolute component ids
    rule: PolicyJson | None
    statement: Text
    location: Location


@dataclass(frozen=True)
class Decision:
    id: DecisionId
    variant: DecisionVariant
    status: DecisionStatus
    affects: tuple[Ref, ...]  # absolute component ids
    location: Location


@dataclass(frozen=True)
class Issue:
    """A problem with a single node. arch.check.engine turns issues into findings."""

    location: Location
    field: FieldName | None
    message: Text


@dataclass(frozen=True)
class Design:
    components: Mapping[ComponentId, Component]
    needs: Mapping[NeedId, Need]
    constraints: Mapping[ConstraintId, Constraint]
    decisions: Mapping[DecisionId, Decision]
    issues: tuple[Issue, ...]


class FieldType(enum.Enum):
    TEXT = "text"
    REFS = "list of references"
    ENUM = "enum"
    MAPPING = "mapping"


@dataclass(frozen=True)
class FieldSpec:
    type: FieldType
    required: bool = False
    choices: tuple[str, ...] = ()


def _enum(cls: type[enum.Enum], required: bool = False) -> FieldSpec:
    return FieldSpec(FieldType.ENUM, required, tuple(m.value for m in cls))


# Frontmatter fields per kind. `kind` itself is checked by the codec; ids come from paths.
FIELDS: Mapping[Kind, Mapping[str, FieldSpec]] = {
    Kind.COMPONENT: {
        "realizes": FieldSpec(FieldType.TEXT, required=True),
        "solution": FieldSpec(FieldType.TEXT, required=True),
        "hides": FieldSpec(FieldType.TEXT),
        "serves": FieldSpec(FieldType.REFS),
        "uses": FieldSpec(FieldType.REFS),
        "exports": FieldSpec(FieldType.REFS),
        "status": _enum(Status, required=True),
    },
    Kind.NEED: {
        "stakeholder": FieldSpec(FieldType.TEXT),
        "signal": FieldSpec(FieldType.TEXT),
    },
    Kind.CONSTRAINT: {
        "applies_to": FieldSpec(FieldType.REFS, required=True),
        "rule": FieldSpec(FieldType.MAPPING),
    },
    Kind.DECISION: {
        "status": _enum(DecisionStatus, required=True),
        "affects": FieldSpec(FieldType.REFS),
        # contradiction-only fields; free text for now
        "improving": FieldSpec(FieldType.TEXT),
        "worsening": FieldSpec(FieldType.TEXT),
        "principles": FieldSpec(FieldType.REFS),
    },
}


def validate_fields(kind: Kind, raw: Mapping[str, object], location: Location) -> tuple[Issue, ...]:
    """Check a node's raw frontmatter against its kind's field specs. Never raises."""
    specs = FIELDS[kind]
    issues: list[Issue] = []
    for name in sorted(set(raw) - set(specs) - {"kind"}):
        issues.append(Issue(location, FieldName(name), Text(f"unknown field '{name}' for a {kind.value}")))
    for name, spec in specs.items():
        if name not in raw or raw[name] is None:
            if spec.required:
                issues.append(Issue(location, FieldName(name), Text(f"missing required field '{name}'")))
            continue
        value = raw[name]
        ok = {
            FieldType.TEXT: isinstance(value, str) and value.strip() != "",
            FieldType.REFS: isinstance(value, list) and all(isinstance(v, str) and v for v in value),
            FieldType.ENUM: isinstance(value, str) and value in spec.choices,
            FieldType.MAPPING: isinstance(value, Mapping),
        }[spec.type]
        if not ok:
            expected = f"one of {', '.join(spec.choices)}" if spec.type is FieldType.ENUM else spec.type.value
            issues.append(Issue(location, FieldName(name), Text(f"field '{name}' must be {expected}")))
    return tuple(issues)
