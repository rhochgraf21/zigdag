"""Which component each source unit belongs to.

Realizes arch.realize.mapping. A component's code path is its id (see arch.model's "Ids are paths"); a unit belongs
to the component whose code path is the longest dotted prefix of the unit's name. Test units are
evidence, not parts of components, and are never mapped.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from arch.model.graph import Graph
from arch.model.ids import ComponentId
from arch.realize.facts import Facts, Import, ImportForm, Role, Unit, UnitName


@dataclass(frozen=True)
class UnitIndex:
    """Which units exist and which names they re-export: enough to resolve imports without a design."""

    known_units: frozenset[UnitName] = frozenset()
    bound_names: frozenset[tuple[UnitName, str]] = frozenset()  # (unit, name) it re-exports

    @staticmethod
    def of(facts: Facts) -> UnitIndex:
        return UnitIndex(frozenset(u.name for u in facts.units), frozenset((a.unit, a.name) for a in facts.aliases))

    def target_of(self, imp: Import) -> UnitName | None:
        """The project unit an import reaches. `from p import n` reaches p itself when p binds n."""
        head, _, name = imp.target.rpartition(".")
        if imp.form is ImportForm.NAME and (UnitName(head), name) in self.bound_names:
            return UnitName(head)
        return self.resolve(imp.target)

    def resolve(self, target: UnitName) -> UnitName | None:
        """The longest prefix of an import target that names a project unit."""
        name = target
        while name:
            if name in self.known_units:
                return name
            name = UnitName(name.rpartition(".")[0])
        return None


@dataclass(frozen=True)
class UnitMap:
    component_of: Mapping[UnitName, ComponentId]
    unmapped: tuple[Unit, ...]
    index: UnitIndex = field(default_factory=UnitIndex)

    def target_of(self, imp: Import) -> UnitName | None:
        return self.index.target_of(imp)

    def resolve(self, target: UnitName) -> UnitName | None:
        return self.index.resolve(target)

    def units_in(self, cid: ComponentId) -> tuple[UnitName, ...]:
        return tuple(sorted(u for u, c in self.component_of.items() if c == cid or c.startswith(cid + ".")))


def map_units(graph: Graph, facts: Facts) -> UnitMap:
    ids = set(graph.ids())
    mapped: dict[UnitName, ComponentId] = {}
    unmapped: list[Unit] = []
    for unit in facts.units:
        if unit.role is Role.TEST:
            continue
        name = unit.name
        while name and name not in ids:
            name = UnitName(name.rpartition(".")[0])
        if name:
            mapped[unit.name] = ComponentId(name)
        else:
            unmapped.append(unit)
    return UnitMap(mapped, tuple(unmapped), UnitIndex.of(facts))
