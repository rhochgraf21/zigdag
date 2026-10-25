"""How to reason well at each design step, independent of any tool surface (arch.guide.method).

Methods are typed objects: steps name abstract operations in model terms, never commands, so any surface
can render them (arch.integrate.agent turns them into agent skills).
"""

from __future__ import annotations

from arch.guide.method.coupling import RESOLVE_COUPLING
from arch.guide.method.critique import CRITIQUE
from arch.guide.method.decompose import DECOMPOSE
from arch.guide.method.elicit import ELICIT_NEEDS
from arch.guide.method.model import AbstractOp, Method, MethodName, Step, WorkedExample
from arch.guide.method.requirements import WRITE_REQUIREMENTS
from arch.guide.method.review import REVIEW_DESIGN_DIFF

METHODS: tuple[Method, ...] = (ELICIT_NEEDS, WRITE_REQUIREMENTS, DECOMPOSE, RESOLVE_COUPLING, REVIEW_DESIGN_DIFF,
                               CRITIQUE)


def method(name: MethodName) -> Method:
    return next(m for m in METHODS if m.name is name)


__all__ = ["METHODS", "AbstractOp", "Method", "MethodName", "Step", "WorkedExample", "method"]
