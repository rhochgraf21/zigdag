"""arch: design-as-code and architecture-as-code for humans and coding agents."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from arch.model.schema import CriterionId

F = TypeVar("F", bound=Callable[..., object])


def realizes(*criteria: CriterionId | str) -> Callable[[F], F]:
    """Link code (a port, contract or test) to the acceptance criteria it realizes, e.g. "x.y#AC2".

    Read statically by arch's adapters; at runtime it only records the links on the object.
    """

    def mark(obj: F) -> F:
        existing = getattr(obj, "__arch_realizes__", ())
        obj.__arch_realizes__ = (*existing, *(CriterionId(c) for c in criteria))  # type: ignore[attr-defined]
        return obj

    return mark


__all__ = ["realizes"]
