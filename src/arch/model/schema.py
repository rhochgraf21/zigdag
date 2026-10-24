"""Node kinds, their fields, and what makes a single node valid.

Realizes arch.model.schema. Hides field representation and per-field validation.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

from arch.model.ids import (
    ComponentId,
    ConstraintId,
    CriterionId,
    DesignPath,
    FieldName,
    Issue,
    Location,
    NeedId,
    Ref,
    Text,
)
from arch.model.policy import Policy

SourceText = str  # the raw contents of a design file


class Kind(enum.Enum):
    NEED = "need"
    COMPONENT = "component"
    CONSTRAINT = "constraint"


class Status(enum.Enum):
    """Component maturity. Checks tighten as a component moves down this list."""

    DRAFT = "draft"
    SPECIFIED = "specified"
    CONTRACTED = "contracted"
    VERIFIED = "verified"

    @property
    def rank(self) -> int:
        return list(Status).index(self)


@dataclass(frozen=True)
class Criterion:
    id: CriterionId
    text: Text
    location: Location


class DecisionLabel(enum.Enum):
    """Labelled lines of a decision entry, written `- Chose: ...`. Chose and Because are expected."""

    CHOSE = "Chose"
    OVER = "Over"
    BECAUSE = "Because"
    CONSEQUENCES = "Consequences"
    PREVIOUSLY = "Previously"
    BACKED_BY = "Backed by"


@dataclass(frozen=True)
class DecisionEntry:
    """One `### title` entry under a component's `## Decisions` section: the DP choice and why."""

    title: Text
    text: Text
    labels: frozenset[DecisionLabel]
    location: Location


@dataclass(frozen=True)
class Suppression:
    """A finding the authors decided to accept on this node, with their reason (`suppress:` in frontmatter)."""

    rule: Text
    reason: Text | None  # None: no reason given, which is itself reported


@dataclass(frozen=True)
class Component:
    id: ComponentId
    realizes: Text
    solution: Text
    hides: Text | None
    serves: tuple[NeedId, ...]
    uses: tuple[Ref, ...]
    exports: tuple[Ref, ...]
    accepts_coupling: tuple[tuple[Ref, ...], ...]  # sets of children whose coupling is accepted
    status: Status
    criteria: tuple[Criterion, ...]
    decisions: tuple[DecisionEntry, ...]
    location: Location
    suppressions: tuple[Suppression, ...] = ()


@dataclass(frozen=True)
class Need:
    id: NeedId
    statement: Text
    stakeholder: Text | None
    signal: Text | None
    location: Location
    suppressions: tuple[Suppression, ...] = ()


@dataclass(frozen=True)
class Constraint:
    id: ConstraintId
    applies_to: tuple[ComponentId, ...]  # absolute ids
    policy: Policy
    statement: Text
    location: Location


@dataclass(frozen=True)
class Design:
    components: Mapping[ComponentId, Component]
    needs: Mapping[NeedId, Need]
    constraints: Mapping[ConstraintId, Constraint]
    issues: tuple[Issue, ...]
    sources: Mapping[DesignPath, SourceText]  # every node file as read, for lossless edits


class FieldType(enum.Enum):
    TEXT = "text"
    REFS = "list of references"
    REF_SETS = "list of lists of at least two child names"
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
        "accepts_coupling": FieldSpec(FieldType.REF_SETS),
        "status": _enum(Status, required=True),
        "suppress": FieldSpec(FieldType.MAPPING),
    },
    Kind.NEED: {
        "stakeholder": FieldSpec(FieldType.TEXT),
        "signal": FieldSpec(FieldType.TEXT),
        "suppress": FieldSpec(FieldType.MAPPING),
    },
    Kind.CONSTRAINT: {
        "applies_to": FieldSpec(FieldType.REFS, required=True),
        "rule": FieldSpec(FieldType.MAPPING),
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
            FieldType.REF_SETS: isinstance(value, list)
            and all(isinstance(s, list) and len(s) >= 2 and all(isinstance(v, str) and v for v in s) for s in value),
            FieldType.ENUM: isinstance(value, str) and value in spec.choices,
            FieldType.MAPPING: isinstance(value, Mapping),
        }[spec.type]
        if not ok:
            expected = f"one of {', '.join(spec.choices)}" if spec.type is FieldType.ENUM else spec.type.value
            issues.append(Issue(location, FieldName(name), Text(f"field '{name}' must be {expected}")))
    return tuple(issues)
