"""arch: design-as-code and architecture-as-code for humans and coding agents."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from typing import TypeAlias

from arch.model.ids import CriterionId

F = TypeVar("F", bound=Callable[..., object])
CriterionRef: TypeAlias = str  # "component#ACn" (or just "component") as written in the decorator


def realizes(*criteria: CriterionRef) -> Callable[[F], F]:
    """Link code (a port, contract or test) to the acceptance criteria it realizes, e.g. "x.y#AC2".

    Read statically by arch's adapters; at runtime it only records the links on the object.
    """

    def mark(obj: F) -> F:
        existing = getattr(obj, "__arch_realizes__", ())
        obj.__arch_realizes__ = (*existing, *(CriterionId(c) for c in criteria))  # type: ignore[attr-defined]
        return obj

    return mark


__all__ = ["realizes"]
