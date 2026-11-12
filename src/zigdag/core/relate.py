"""Working out relationships (DESIGN2 §2.4) from the code model and the DP tree: dependencies between DPs, the
design matrix at each level, and the effects each place reaches through calls.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

import deal

from zigdag.core.effects import Effect
from zigdag.core.resolve import DEPLOYED, Tree
from zigdag.core.code import (
    CodeModel,
    Dependency,
    DependencyKind,
    Place,
    Qualified,
    ResourceUse,
    SymbolKind,
    SymbolName,
    TestId,
)
from zigdag.core.findings import Span
from zigdag.core.names import CodePath, FrName
from zigdag.core.names import Api


class Where(enum.Enum):
    PROJECT = "project"
    VENDORED = "vendored"
    STANDARD = "standard library"
    THIRD_PARTY = "third party"


@dataclass(frozen=True)
class Target:
    where: Where
    top: str  # the top-level package, for libraries
    unit: CodePath | None = None
    owner: FrName | None = None


@deal.ensure(lambda model, tree, name, result: result.top == name.split(".")[0])
@deal.ensure(lambda model, tree, name, result: (result.unit is not None) == (result.where is Where.PROJECT))
@deal.ensure(lambda model, tree, name, result: result.owner is None or result.where is Where.PROJECT)
def classify(model: CodeModel, tree: Tree, name: Qualified) -> Target:
    top = name.split(".")[0]
    vendored = model.libraries.vendored
    if top in vendored or any(name == v or name.startswith(v + ".") for v in vendored if "." in v):
        return Target(Where.VENDORED, top)
    unit = model.unit_of(name)
    if unit is not None:
        return Target(Where.PROJECT, top, unit, tree.owner(name))
    if top in model.libraries.standard:
        return Target(Where.STANDARD, top)
    return Target(Where.THIRD_PARTY, top)


@dataclass(frozen=True)
class Edge:
    """One dependency of a place in one DP on code in another DP."""

    source: FrName
    target: FrName
    dependency: Dependency

    @property
    @deal.ensure(lambda self, result: result == self.dependency.source)
    def place(self) -> Place:
        """The code that depends."""
        return self.dependency.source

    @property
    @deal.ensure(lambda self, result: result == self.dependency.target)
    def target_name(self) -> Qualified:
        """What it depends on, as the code names it."""
        return self.dependency.target

    @property
    @deal.ensure(lambda self, result: result == self.dependency.span)
    def span(self) -> Span:
        return self.dependency.span

    @property
    @deal.ensure(lambda self, result: result == (self.dependency.kind is DependencyKind.IMPORT))
    def is_import(self) -> bool:
        return self.dependency.kind is DependencyKind.IMPORT


@dataclass(frozen=True)
class Origin:
    """Where an effect starts, and the API it starts with."""

    place: Place
    via: str
    span: Span
    seen: TestId | None = None  # seen while this test ran, rather than read from the code

    @property
    def how(self) -> str:
        """The API it starts with, and when it was seen: "open, seen while tests.test_io::test_save ran"."""
        return f"{self.via}, seen while {self.seen} ran" if self.seen else self.via


@dataclass(frozen=True)
class ResourceEffect:
    """A call to a client of a deployed resource, with the resource it is on: the resource effect it is (DESIGN2 §3,
    §5.3)."""

    use: ResourceUse
    container: FrName  # the container whose code makes the call
    on: FrName  # the container read or written
    effect: Effect  # shop.receipts.write


@dataclass(frozen=True)
class Relations:
    edges: tuple[Edge, ...]
    effects: Mapping[Place, Mapping[Effect, frozenset[Origin]]]  # direct and reached through calls
    places: Mapping[Place, FrName]  # every place with code, and the DP it belongs to
    resource_effects: tuple[ResourceEffect, ...] = ()  # where the infrastructure is described
    untraced: tuple[ResourceUse, ...] = ()  # calls to a resource's client whose resource could not be told

    @deal.ensure(lambda self, place, result: (result is None) == (place not in self.places))
    def dp_of(self, place: Place) -> FrName | None:
        """The DP whose code a place is."""
        return self.places.get(place)

    @deal.pre(lambda self, tree, parent: parent in tree.dps)
    @deal.ensure(lambda self, tree, parent, result: result[0] == tree.dps[parent].children)
    @deal.ensure(lambda self, tree, parent, result: all(a != b and a in result[0] and b in result[0]
                                                        and edge in self.edges for (a, b), edge in result[1].items()))
    def matrix(self, tree: Tree, parent: FrName) -> tuple[tuple[FrName, ...], Mapping[tuple[FrName, FrName], Edge]]:
        """The siblings under parent, and for each pair (a, b) one edge showing a depends on b."""
        order = tree.dps[parent].children
        cells: dict[tuple[FrName, FrName], Edge] = {}
        for edge in self.edges:
            a = next((c for c in order if tree.within(edge.source, c)), None)
            b = next((c for c in order if tree.within(edge.target, c)), None)
            if a and b and a != b:
                cells.setdefault((a, b), edge)
        return order, cells


def _callable(model: CodeModel, name: Qualified) -> list[Place]:
    """The places a call to this name runs: a function or method, or a class's constructor."""
    symbol = model.symbols.get(name)
    if symbol is None:
        return []
    if symbol.kind is SymbolKind.CLASS:
        return [Place(symbol.unit, SymbolName(f"{symbol.name}.{m}")) for m in ("__init__", "__post_init__")
                if Qualified(f"{name}.{m}") in model.symbols]
    if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
        return [Place(symbol.unit, symbol.name)]
    return []


def _places_in(model: CodeModel) -> set[Place]:
    return {*(d.source for d in model.dependencies), *(c.caller for c in model.calls), *(e.at for e in model.effects),
            *(u.at for u in model.unknowns), *(a.at for a in model.accesses), *(u.at for u in model.uses),
            *(r.at for r in model.raises)}


def _resource_effects(model: CodeModel, tree: Tree,
                      places: Mapping[Place, FrName]) -> tuple[list[ResourceEffect], list[ResourceUse]]:
    """Each call to a resource's client as the resource effect it is, and the calls whose resource cannot be told.
    The resource's name reaches the call through a setting, and the infrastructure says which resource the setting
    of that container points at (DESIGN2 §5.3). A project that describes no infrastructure has no resource effects."""
    if not any(unit.kind in DEPLOYED for unit in model.units.values()):
        return [], []
    found: list[ResourceEffect] = []
    untraced: list[ResourceUse] = []
    for use in model.resource_uses:
        dp = places.get(use.at)
        container = tree.container_of(dp) if dp is not None else None
        # A setting given to a unit the whole system owns, such as a shared role, is every container's.
        targets = sorted({tree.unit_owner[s.target] for s in model.settings
                          if container is not None and s.name == use.setting and s.target in tree.unit_owner
                          and (given_to := tree.unit_owner.get(s.at)) is not None and tree.within(container, given_to)})
        if container is None or not targets:
            untraced.append(use)
        found += [ResourceEffect(use, container, on, Effect(f"{on}.{use.access.value}")) for on in targets
                  if container is not None]
    return found, untraced


@deal.ensure(lambda model, tree, custom_calls, result: all(e.source != e.target for e in result.edges))
@deal.ensure(lambda model, tree, custom_calls, result: all(  # every effect a place has directly, it has in the end
    e.effect in result.effects.get(e.at, {}) for e in model.effects))
def relate(model: CodeModel, tree: Tree, custom_calls: Mapping[Api, Effect]) -> Relations:
    places: dict[Place, FrName] = {}
    for symbol in model.symbols.values():
        if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD) and (dp := tree.owner(symbol.qualified)):
            places[Place(symbol.unit, symbol.name)] = dp
    for unit in model.units:
        if (dp := tree.owner(unit)) is not None:
            places[Place(unit, None)] = dp
    for place in _places_in(model):  # code the static reading did not define, such as code seen running
        if place not in places and (dp := tree.owner_of(place)) is not None:
            places[place] = dp

    edges = []
    for d in model.dependencies:
        source = places.get(d.source)
        target = classify(model, tree, d.target)
        if source and target.owner and target.owner != source:
            edges.append(Edge(source, target.owner, d))

    effects: dict[Place, dict[Effect, set[Origin]]] = {}
    for e in model.effects:
        effects.setdefault(e.at, {}).setdefault(e.effect, set()).add(Origin(e.at, e.via, e.span, e.seen))
    resource_effects, untraced = _resource_effects(model, tree, places)
    for r in resource_effects:
        effects.setdefault(r.use.at, {}).setdefault(r.effect, set()).add(Origin(r.use.at, r.use.via, r.use.span))
    callers: dict[Place, set[Place]] = {}
    for c in model.calls:
        if c.callee in custom_calls:
            effect = custom_calls[c.callee]
            effects.setdefault(c.caller, {}).setdefault(effect, set()).add(Origin(c.caller, c.callee, c.span, c.seen))
            continue
        for callee in _callable(model, c.callee):
            if callee != c.caller:
                callers.setdefault(callee, set()).add(c.caller)
    work = list(effects)
    while work:
        callee = work.pop()
        found = effects.get(callee, {})
        for caller in callers.get(callee, ()):
            mine = effects.setdefault(caller, {})
            changed = False
            for effect, origins in found.items():
                have = mine.setdefault(effect, set())
                if not origins <= have:
                    have |= origins
                    changed = True
            if changed:
                work.append(caller)
    frozen = {p: {e: frozenset(o) for e, o in found.items()} for p, found in effects.items()}
    return Relations(tuple(edges), frozen, places, tuple(resource_effects), tuple(untraced))
