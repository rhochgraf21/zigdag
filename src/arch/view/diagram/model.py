"""Diagrams as data: boxes, nesting, edges and marks, built from the design and what is observed.

Part of arch.view.diagram. Renderers (Mermaid, Graphviz) only translate a Diagram; every decision about
what to show is made here, deterministically, so the same design always gives the same diagram.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass, replace

from arch.change.diff import ChangeClass, DesignDiff, NodeChangeType
from arch.check.engine import Report
from arch.model.graph import Graph
from arch.model.ids import ComponentId, Text, is_within, parent_of, short_name
from arch.model.matrix import matrix_of
from arch.model.schema import Status
from arch.realize.facts import Capability, Facts, Role
from arch.realize.history import History
from arch.realize.mapping import map_units
from arch.view.outline import Depth

HIDDEN_COUPLING_MIN_COMMITS = 3


class EdgeKind(enum.Enum):
    DECLARED = "declared"  # a use in the design
    UNDECLARED = "undeclared"  # the code imports it, the design does not say so
    HIDDEN = "hidden"  # changed together repeatedly without a dependency either way


class Mark(enum.Enum):
    """How a node or edge changed relative to a base revision."""

    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class EffectClass(enum.Enum):
    PURE = "pure"  # no effects observed
    EFFECTFUL = "effectful"  # effects within what its constraints allow
    VIOLATING = "violating"  # effects its constraints forbid
    UNKNOWN = "unknown"  # no code yet, or effects not analyzed


class Edges(enum.Enum):
    REDUCED = "reduced"  # omit uses implied by other uses (transitive reduction)
    ALL = "all"


@dataclass(frozen=True)
class Node:
    id: ComponentId
    label: Text
    realizes: Text
    status: Status
    children: tuple[Node, ...] = ()  # drawn inside this node when expanded
    mark: Mark = Mark.UNCHANGED
    effect: EffectClass | None = None  # set by the effects overlay

    def walk(self) -> Iterable[Node]:
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass(frozen=True)
class Edge:
    source: ComponentId  # the user
    target: ComponentId  # what it uses
    kind: EdgeKind = EdgeKind.DECLARED
    mark: Mark = Mark.UNCHANGED


@dataclass(frozen=True)
class Diagram:
    title: Text
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    def all_nodes(self) -> tuple[Node, ...]:
        return tuple(n for top in self.nodes for n in top.walk())

    def node_ids(self) -> frozenset[ComponentId]:
        return frozenset(n.id for n in self.all_nodes())


def _node(graph: Graph, cid: ComponentId, depth: int) -> Node:
    c = graph[cid]
    kids = tuple(_node(graph, k, depth - 1) for k in matrix_of(graph, cid).order) if depth > 1 else ()
    return Node(cid, short_name(cid), c.realizes, c.status, kids)


def _sibling_edges(graph: Graph, parent: ComponentId | None, kids: tuple[ComponentId, ...], edges: Edges) -> list[Edge]:
    if parent is None:
        return []
    m = matrix_of(graph, parent)
    entries = set(m.entries)
    if edges is Edges.REDUCED and not m.layering.coupled:
        entries = _transitive_reduction(entries)
    return [Edge(a, b) for a, b in sorted(entries) if a in kids and b in kids]


def _transitive_reduction(entries: set[tuple[ComponentId, ComponentId]]) -> set[tuple[ComponentId, ComponentId]]:
    """Drop a -> c when a reaches c through other edges. Only valid for acyclic relations."""
    succ: dict[ComponentId, set[ComponentId]] = {}
    for a, b in entries:
        succ.setdefault(a, set()).add(b)

    def reaches(start: ComponentId, goal: ComponentId, skip: tuple[ComponentId, ComponentId]) -> bool:
        seen, todo = set(), [start]
        while todo:
            x = todo.pop()
            for y in succ.get(x, ()):
                if (x, y) == skip or y in seen:
                    continue
                if y == goal:
                    return True
                seen.add(y)
                todo.append(y)
        return False

    return {(a, b) for a, b in entries if not reaches(a, b, (a, b))}


def containment(graph: Graph, root: ComponentId | None = None, depth: Depth = Depth(1),
                edges: Edges = Edges.REDUCED) -> Diagram:
    """`root`'s children as boxes (nested `depth` levels deep), with the uses between siblings at each level.
    Without a root, a single-rooted system is drawn from its root's parts."""
    if root is None and len(graph.roots) == 1:
        root = graph.roots[0]
    tops = graph.children(root) if root is not None else graph.roots
    if root is not None and not tops:
        tops = (root,)
    order = matrix_of(graph, root).order if root is not None and graph.children(root) else tuple(sorted(tops))
    nodes = tuple(_node(graph, c, depth) for c in order)
    out: list[Edge] = _sibling_edges(graph, root, order, edges)
    for n in nodes:
        for inner in n.walk():
            kids = tuple(k.id for k in inner.children)
            if kids:
                out += _sibling_edges(graph, inner.id, kids, edges)
    title = Text(f"{root}" if root else "system")
    return Diagram(title, nodes, tuple(out))


def with_effects(diagram: Diagram, graph: Graph, facts: Facts, report: Report) -> Diagram:
    """Colour each node by what its code does: pure, effectful within its constraints, or violating them."""
    m = map_units(graph, facts)
    source = {u.name: u for u in facts.units if u.role is Role.SOURCE}
    violating = {f.subject for f in report.findings if f.rule in ("C008", "C012") and not report.is_answered(f)}

    def classify(cid: ComponentId) -> EffectClass:
        units = [u for u, c in m.component_of.items() if is_within(c, cid) and u in source]
        if not units or any(Capability.EFFECTS not in source[u].capabilities for u in units):
            return EffectClass.UNKNOWN
        if any(is_within(ComponentId(v), cid) for v in violating):
            return EffectClass.VIOLATING
        return EffectClass.EFFECTFUL if any(e.unit in units for e in facts.effects) else EffectClass.PURE

    def paint(n: Node) -> Node:
        return replace(n, effect=classify(n.id), children=tuple(paint(c) for c in n.children))

    return replace(diagram, nodes=tuple(paint(n) for n in diagram.nodes))


def with_observed(diagram: Diagram, graph: Graph, facts: Facts) -> Diagram:
    """Add undeclared imports and hidden coupling between nodes drawn side by side."""
    m = map_units(graph, facts)
    shown = diagram.node_ids()
    siblings: dict[ComponentId | None, list[ComponentId]] = {}
    for cid in sorted(shown):
        siblings.setdefault(parent_of(cid), []).append(cid)

    def owner(unit_component: ComponentId, group: list[ComponentId]) -> ComponentId | None:
        return next((g for g in group if is_within(unit_component, g)), None)

    declared = {(e.source, e.target) for e in diagram.edges}
    full = {(a, b) for g in siblings.values() for a in g for b in g if a != b and any(is_within(u, b) for u in graph.uses(a))}
    extra: dict[tuple[ComponentId, ComponentId], Edge] = {}
    source = {u.name for u in facts.units if u.role is Role.SOURCE}
    for imp in facts.imports:
        target = m.target_of(imp)
        a_comp, b_comp = m.component_of.get(imp.unit), m.component_of.get(target) if target else None
        if imp.unit not in source or a_comp is None or b_comp is None:
            continue
        for group in siblings.values():
            a, b = owner(a_comp, group), owner(b_comp, group)
            if a and b and a != b and (a, b) not in full:
                extra[(a, b)] = Edge(a, b, EdgeKind.UNDECLARED)
    history = History.of(facts)
    for group in siblings.values():
        members = {g: [u for u, c in m.component_of.items() if is_within(c, g)] for g in group}
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                linked = {(a, b), (b, a)} & (full | set(extra) | declared)
                if not linked and history.co_changes(members[a], members[b]) >= HIDDEN_COUPLING_MIN_COMMITS:
                    extra[(a, b)] = Edge(a, b, EdgeKind.HIDDEN)
    return replace(diagram, edges=diagram.edges + tuple(e for _, e in sorted(extra.items())))


def changes(before: Graph, after: Graph, diff: DesignDiff) -> Diagram:
    """Structural change since `before`: components added, removed, moved, or whose uses, exports or accepted
    couplings changed, plus the components their changed edges connect. Text-only changes are not structure."""
    marks: dict[ComponentId, Mark] = {}
    for c in diff.changes:
        structural = c.type is not NodeChangeType.CHANGED or ChangeClass.STRUCTURE in c.classes
        if c.kind.value != "component" or not structural:
            continue
        mark = {NodeChangeType.ADDED: Mark.ADDED, NodeChangeType.REMOVED: Mark.REMOVED,
                NodeChangeType.MOVED: Mark.CHANGED, NodeChangeType.CHANGED: Mark.CHANGED}[c.type]
        marks[ComponentId(c.ident)] = mark
    if not marks:
        return Diagram(Text("no component changes"), (), ())

    def uses(g: Graph, cid: ComponentId) -> set[ComponentId]:
        return set(g.uses(cid)) if cid in g else set()

    old = {(a, b) for a in marks for b in uses(before, a)} | {(a, b) for b in marks for a in before.users_of(b) if b in before}
    new = {(a, b) for a in marks for b in uses(after, a)} | {(a, b) for b in marks for a in after.users_of(b) if b in after}
    changed_edges = old ^ new
    shown = set(marks) | {x for edge in changed_edges for x in edge}
    old = {e for e in old if e[0] in shown and e[1] in shown}
    new = {e for e in new if e[0] in shown and e[1] in shown}
    edges = [Edge(a, b, EdgeKind.DECLARED, Mark.ADDED if (a, b) not in old else Mark.REMOVED if (a, b) not in new
                  else Mark.UNCHANGED) for a, b in sorted(old | new)]

    def node(cid: ComponentId) -> Node:
        g = after if cid in after else before
        c = g[cid]
        return Node(cid, Text(cid), c.realizes, c.status, (), marks.get(cid, Mark.UNCHANGED))

    return Diagram(Text("design changes"), tuple(node(c) for c in sorted(shown)), tuple(edges))
