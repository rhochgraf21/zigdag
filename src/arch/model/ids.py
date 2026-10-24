"""Identifiers, text and places in the design: the vocabulary every other part of the model uses.

Realizes arch.model.ids. Hides how ids are spelled and compared.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

ComponentId = NewType("ComponentId", str)  # dotted path under design/components/
NeedId = NewType("NeedId", str)
ConstraintId = NewType("ConstraintId", str)
CriterionId = NewType("CriterionId", str)  # "<component id>#ACn"
CriterionLabel = NewType("CriterionLabel", str)  # "ACn"
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
