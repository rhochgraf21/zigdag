"""Design matrices: classify a component's children and order them for realization.

Realizes arch.model.matrix. Declared sibling uses are the off-diagonal entries: a cycle is a
coupled set, an acyclic matrix is decoupled, and no entries at all is uncoupled.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

import deal

from arch.model.graph import Graph, is_within
from arch.model.schema import ComponentId

N = TypeVar("N", bound=str)


@dataclass(frozen=True)
class Layering(Generic[N]):
    """Nodes grouped so that each layer depends only on earlier layers.

    A coupled set (cycle) occupies a single layer together; its members appear in `coupled`.
    """

    layers: tuple[tuple[N, ...], ...]
    coupled: tuple[tuple[N, ...], ...]

    @property
    def order(self) -> tuple[N, ...]:
        return tuple(n for layer in self.layers for n in layer)


def _is_permutation(nodes: Collection[N], result: Layering[N]) -> bool:
    return sorted(result.order) == sorted(set(nodes))


@deal.has()
@deal.ensure(lambda nodes, deps, result: _is_permutation(nodes, result))
def layer(nodes: Collection[N], deps: Callable[[N], Iterable[N]]) -> Layering[N]:
    """Layer `nodes` by longest dependency path; ties sorted, so the result is deterministic."""
    members = sorted(set(nodes))
    member_set = set(members)
    edges = {n: sorted({d for d in deps(n) if d in member_set and d != n}) for n in members}

    sccs = _strongly_connected(members, edges)  # dependencies come before dependents
    scc_of = {n: i for i, scc in enumerate(sccs) for n in scc}
    depth: list[int] = []
    for i, scc in enumerate(sccs):
        below = [depth[scc_of[d]] for n in scc for d in edges[n] if scc_of[d] != i]
        depth.append(1 + max(below, default=-1))

    grouped: dict[int, list[N]] = {}
    for i, scc in enumerate(sccs):
        grouped.setdefault(depth[i], []).extend(scc)
    layers = tuple(tuple(sorted(grouped[k])) for k in sorted(grouped))
    coupled = tuple(sorted(scc for scc in sccs if len(scc) > 1))
    return Layering(layers, coupled)


def _strongly_connected(nodes: list[N], edges: dict[N, list[N]]) -> list[tuple[N, ...]]:
    """Tarjan's algorithm, iterative. Emits each SCC after every SCC it depends on."""
    index: dict[N, int] = {}
    low: dict[N, int] = {}
    stack: list[N] = []
    on_stack: set[N] = set()
    out: list[tuple[N, ...]] = []

    for root in nodes:
        if root in index:
            continue
        index[root] = low[root] = len(index)
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(edges[root]))]
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = len(index)
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(edges[w])))
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    u = work[-1][0]
                    low[u] = min(low[u], low[v])
                if low[v] == index[v]:
                    scc: list[N] = []
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        scc.append(w)
                        if w == v:
                            break
                    out.append(tuple(sorted(scc)))
    return out


class Coupling(enum.Enum):
    UNCOUPLED = "uncoupled"
    DECOUPLED = "decoupled"
    COUPLED = "coupled"


@dataclass(frozen=True)
class Matrix:
    parent: ComponentId
    entries: frozenset[tuple[ComponentId, ComponentId]]  # (row uses column), off-diagonal only
    layering: Layering[ComponentId]

    @property
    def order(self) -> tuple[ComponentId, ...]:
        return self.layering.order

    @property
    def coupling(self) -> Coupling:
        if self.layering.coupled:
            return Coupling.COUPLED
        return Coupling.DECOUPLED if self.entries else Coupling.UNCOUPLED


@deal.has()
def matrix_of(graph: Graph, parent: ComponentId) -> Matrix:
    """The design matrix of `parent`'s children. A use of a sibling's descendant counts as using the sibling."""
    kids = graph.children(parent)
    entries = frozenset(
        (row, col)
        for row in kids
        for col in kids
        if row != col and any(is_within(u, col) for u in graph.uses(row))
    )
    deps = {k: [c for r, c in entries if r == k] for k in kids}
    return Matrix(parent, entries, layer(kids, deps.__getitem__))
