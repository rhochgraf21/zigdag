"""What a method is: steps toward a design result, naming abstract operations, never commands.

Part of arch.guide.method.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

from arch.model.ids import DesignPath, Text
from arch.model.schema import SourceText


class AbstractOp(enum.Enum):
    """Operations in model terms. Surfaces (arch.integrate.agent) map each to a concrete command."""

    CONTEXT = "see the context of a component or file"
    OUTLINE = "see the decomposition"
    MATRIX = "see a component's design matrix"
    OBSERVED_MATRIX = "see declared coupling next to observed imports and co-change"
    PLAN = "see the impact of a change and the order to make it"
    CHECK = "check the design and the code"
    NEXT = "see the most valuable next actions"
    DIFF = "see how the design changed"
    ADD_NEED = "add a need"
    ADD_COMPONENT = "add a component"
    ADD_CRITERION = "add an acceptance criterion"
    ADD_DECISION = "record a decision"
    SET_FIELD = "change a field"
    LINK = "add a reference (uses, exports, serves)"
    UNLINK = "remove a reference"
    MOVE = "move or rename a component"
    REMOVE = "remove a node"


class MethodName(enum.Enum):
    ELICIT_NEEDS = "elicit-needs"
    WRITE_REQUIREMENTS = "write-requirements"
    DECOMPOSE = "decompose"
    RESOLVE_COUPLING = "resolve-coupling"
    REVIEW_DESIGN_DIFF = "review-design-diff"


@dataclass(frozen=True)
class Step:
    text: Text
    uses: tuple[AbstractOp, ...] = ()


@dataclass(frozen=True)
class WorkedExample:
    situation: Text
    result: Mapping[DesignPath, SourceText]  # the design files the method produces; they pass `arch check`
    lesson: Text


@dataclass(frozen=True)
class Method:
    name: MethodName
    title: Text
    when: Text  # when to use it, for agents deciding whether it applies
    inputs: tuple[Text, ...]
    steps: tuple[Step, ...]
    exit_criteria: tuple[Text, ...]
    self_check: tuple[Step, ...]  # always ends with the deterministic check
    example: WorkedExample

    @property
    def operations(self) -> frozenset[AbstractOp]:
        return frozenset(op for s in (*self.steps, *self.self_check) for op in s.uses)
