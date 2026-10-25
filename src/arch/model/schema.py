"""Node kinds, their fields, and what makes a single node valid.

Realizes arch.model.schema. Hides field representation and per-field validation.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

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
RawFrontmatter: TypeAlias = Mapping[str, object]  # a node's frontmatter as read from YAML, before validation


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
class Component:
    id: ComponentId
    realizes: Text
    solution: Text
    hides: Text | None  # a decision it keeps from the other parts (Parnas)
    serves: tuple[NeedId, ...]
    uses: tuple[Ref, ...]
    exports: tuple[Ref, ...]
    status: Status
    criteria: tuple[Criterion, ...]
    decisions: tuple[DecisionEntry, ...]
    location: Location
    publishes: Text | None = None  # a vocabulary the other parts build against (a design rule)


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
    ENUM = "enum"
    MAPPING = "mapping"


class Presence(enum.Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class FieldSpec:
    type: FieldType
    presence: Presence = Presence.OPTIONAL
    choices: tuple[Text, ...] = ()


def _enum(cls: type[enum.Enum], presence: Presence = Presence.OPTIONAL) -> FieldSpec:
    return FieldSpec(FieldType.ENUM, presence, tuple(Text(m.value) for m in cls))


# Frontmatter fields per kind. `kind` itself is checked by the codec; ids come from paths.
FIELDS: Mapping[Kind, Mapping[str, FieldSpec]] = {
    Kind.COMPONENT: {
        "realizes": FieldSpec(FieldType.TEXT, Presence.REQUIRED),
        "solution": FieldSpec(FieldType.TEXT, Presence.REQUIRED),
        "hides": FieldSpec(FieldType.TEXT),
        "publishes": FieldSpec(FieldType.TEXT),
        "serves": FieldSpec(FieldType.REFS),
        "uses": FieldSpec(FieldType.REFS),
        "exports": FieldSpec(FieldType.REFS),
        "status": _enum(Status, Presence.REQUIRED),
    },
    Kind.NEED: {
        "stakeholder": FieldSpec(FieldType.TEXT),
        "signal": FieldSpec(FieldType.TEXT),
    },
    Kind.CONSTRAINT: {
        "applies_to": FieldSpec(FieldType.REFS, Presence.REQUIRED),
        "rule": FieldSpec(FieldType.MAPPING),
    },
}


def validate_fields(kind: Kind, raw: RawFrontmatter, location: Location) -> tuple[Issue, ...]:
    """Check a node's raw frontmatter against its kind's field specs. Never raises."""
    specs = FIELDS[kind]
    issues: list[Issue] = []
    for name in sorted(set(raw) - set(specs) - {"kind"}):
        issues.append(Issue(location, FieldName(name), Text(f"unknown field '{name}' for a {kind.value}")))
    for name, spec in specs.items():
        if name not in raw or raw[name] is None:
            if spec.presence is Presence.REQUIRED:
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
