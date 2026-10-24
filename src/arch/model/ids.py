"""Identifiers, text and places in the design: the vocabulary every other part of the model uses.

Realizes arch.model.ids. Hides how ids are spelled and compared.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import NewType

ComponentId = NewType("ComponentId", str)  # dotted path under design/components/
NeedId = NewType("NeedId", str)
ConstraintId = NewType("ConstraintId", str)
CriterionId = NewType("CriterionId", str)  # "<component id>#ACn"
CriterionLabel = NewType("CriterionLabel", str)  # "ACn"
NodeId = NewType("NodeId", str)  # the id of any node: a component, need or constraint
Ref = NewType("Ref", str)  # a component reference as written; arch.model.graph resolves it
Text = NewType("Text", str)
FieldName = NewType("FieldName", str)
DesignPath = NewType("DesignPath", str)  # '/'-separated, relative to the design root
LineNo = NewType("LineNo", int)


def parent_of(cid: ComponentId) -> ComponentId | None:
    head, sep, _ = cid.rpartition(".")
    return ComponentId(head) if sep else None


def is_within(inner: ComponentId, outer: ComponentId) -> bool:
    """True if `inner` is `outer` or one of its descendants."""
    return inner == outer or inner.startswith(outer + ".")


def ancestors_of(cid: ComponentId) -> tuple[ComponentId, ...]:
    out = []
    p = parent_of(cid)
    while p is not None:
        out.append(p)
        p = parent_of(p)
    return tuple(out)


def resolve_in(ids: Collection[ComponentId], cid: ComponentId, ref: Ref) -> ComponentId | None:
    """Lexical scoping: `ref` written in `cid` names the nearest ancestor's descendant at path `ref`."""
    for anc in ancestors_of(cid):
        candidate = ComponentId(f"{anc}.{ref}")
        if candidate in ids:
            return candidate
    return None


def reference_in(ids: Collection[ComponentId], cid: ComponentId, target: ComponentId) -> Ref | None:
    """The shortest reference that, written in `cid`, resolves to `target`."""
    segments = target.split(".")
    for k in range(1, len(segments) + 1):
        ref = Ref(".".join(segments[-k:]))
        if resolve_in(ids, cid, ref) == target:
            return ref
    return None


def common_ancestor(a: ComponentId, b: ComponentId) -> ComponentId | None:
    """The deepest component containing both (either may be it)."""
    shared = []
    for x, y in zip(a.split("."), b.split(".")):
        if x != y:
            break
        shared.append(x)
    return ComponentId(".".join(shared)) if shared else None


def short_name(cid: ComponentId) -> Text:
    return Text(cid.rpartition(".")[2])


def criterion_id(cid: ComponentId, label: CriterionLabel) -> CriterionId:
    return CriterionId(f"{cid}#{label}")


def split_criterion(target: Text) -> tuple[ComponentId, CriterionLabel | None]:
    """`x.y#AC2` -> (x.y, AC2); `x.y` -> (x.y, None)."""
    component, _, label = target.partition("#")
    return ComponentId(component), CriterionLabel(label) if label else None


@dataclass(frozen=True, order=True)
class Location:
    path: DesignPath
    line: LineNo = LineNo(1)

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Issue:
    """A problem with a single node. arch.check.engine turns issues into findings."""

    location: Location
    field: FieldName | None
    message: Text
