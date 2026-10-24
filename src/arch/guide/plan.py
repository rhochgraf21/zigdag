"""Impact of changing components, and which work can proceed in parallel and in what order.

Realizes arch.guide.plan. Layers come from declared uses among leaves; components in one layer have
no uses between them, so they can go to separate agents.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from arch.model.graph import Graph, is_within
from arch.model.matrix import Layering, layer
from arch.model.schema import ComponentId


@dataclass(frozen=True)
class Plan:
    targets: tuple[ComponentId, ...]
    impacted: tuple[ComponentId, ...]  # leaves that use a target, directly or transitively
    layering: Layering[ComponentId]


def plan(graph: Graph, targets: Iterable[ComponentId] = ()) -> Plan:
    leaves = graph.leaves

    def deps(c: ComponentId) -> list[ComponentId]:
        return [leaf for u in graph.uses(c) for leaf in leaves if is_within(leaf, u)]

    targets = tuple(sorted(set(targets)))
    if not targets:
        return Plan((), (), layer(leaves, deps))

    scope = {leaf for leaf in leaves if any(is_within(leaf, t) for t in targets)}
    users = {leaf: deps(leaf) for leaf in leaves}
    impacted: set[ComponentId] = set()
    frontier = set(scope)
    while frontier:
        frontier = {u for u, ds in users.items() if u not in scope | impacted and frontier & set(ds)}
        impacted |= frontier
    return Plan(targets, tuple(sorted(impacted)), layer(scope | impacted, deps))
