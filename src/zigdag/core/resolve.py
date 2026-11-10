"""Working out the physical domain (DESIGN2 §2.3, §7.5): each DP's code, its level, and who owns every unit.

Hides the mapping rules: relative names, defaults, the most specific claim winning, groupings and coverage.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

import deal

from zigdag.core.record.model import Record
from zigdag.core.code import CodeModel, Place, Qualified, SymbolKind
from zigdag.core.findings import Finding, Result, Span, finding
from zigdag.core.names import AdapterName, CodePath, FrName, is_within, parent

COVERAGE = "coverage"
LEVELS = "levels"
PLACEMENT = "placement"


class Level(enum.IntEnum):
    SYSTEM = 0
    CONTAINER = 1
    COMPONENT = 2
    STRUCTURE = 3


@dataclass(frozen=True)
class Claim:
    """A unit a DP is, or a type inside a unit when the DP is a structure."""

    unit: CodePath
    type: Qualified | None = None


@dataclass(frozen=True)
class Dp:
    name: FrName
    parent: FrName | None
    children: tuple[FrName, ...]
    claims: tuple[Claim, ...]
    level: Level | None  # None: no code yet, and no children


@dataclass(frozen=True)
class Tree:
    dps: Mapping[FrName, Dp]
    unit_owner: Mapping[CodePath, FrName]
    type_owner: Mapping[Qualified, FrName]

    @deal.ensure(lambda self, name, result: result is None or result in {*self.unit_owner.values(),
                                                                          *self.type_owner.values()})
    def owner(self, name: Qualified | CodePath) -> FrName | None:
        """The DP a unit, or a name inside one, belongs to: a structure's own type first, then the unit."""
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            prefix = ".".join(parts[:i])
            if (dp := self.type_owner.get(Qualified(prefix))) is not None:
                return dp
            if (dp := self.unit_owner.get(CodePath(prefix))) is not None:
                return dp
        return None

    @deal.ensure(lambda self, place, result: result == self.owner(Qualified(str(place))))  # code runs where it is
    def owner_of(self, place: Place) -> FrName | None:
        return self.owner(Qualified(str(place)))

    @deal.ensure(lambda self, name, ancestor, result: result == is_within(name, ancestor))  # as the record reads it
    def within(self, name: FrName, ancestor: FrName) -> bool:
        return name == ancestor or name.startswith(ancestor + ".")

    @deal.ensure(lambda self, name, result: result <= set(self.dps) and (name in result) == (name in self.dps))
    @deal.ensure(lambda self, name, result: all(is_within(n, name) for n in result))
    def subtree(self, name: FrName) -> frozenset[FrName]:
        return frozenset(n for n in self.dps if self.within(n, name))

    @deal.ensure(lambda self, name, result: name in self.dps or result == ())
    def claims_of(self, name: FrName) -> tuple[Qualified, ...]:
        """The code a DP is, as full names: its units and types."""
        dp = self.dps.get(name)
        return tuple(c.type or c.unit for c in dp.claims) if dp else ()

    @deal.ensure(lambda self, name, result: not self.claims_of(name) or result == self.claims_of(name))  # its own first
    @deal.ensure(lambda self, name, result: result == () or result in [self.claims_of(a) for a in self.dps
                                                                         if is_within(name, a)])
    def code_base(self, name: FrName) -> tuple[Qualified, ...]:
        """What code names written for a DP are read relative to: the code of the nearest DP at or above it that has
        code of its own (§7.5)."""
        at: FrName | None = name
        while at is not None:
            if claims := self.claims_of(at):
                return claims
            at = parent(at)
        return ()

    @deal.ensure(lambda self, name, result: all(is_within(n, name) and claims for n, claims in result.items()))
    def claims_under(self, name: FrName) -> dict[FrName, tuple[Qualified, ...]]:
        """The code of every DP at or below a name that has code of its own."""
        return {n: self.claims_of(n) for n in sorted(self.subtree(name)) if self.claims_of(n)}


def _camel(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _claim(model: CodeModel, bases: tuple[str, ...], path: str) -> Claim | None:
    """A unit or type named relative to the bases (or absolutely, when no base has it)."""
    for base in (*bases, ""):
        candidate = f"{base}.{path}" if base else path
        if CodePath(candidate) in model.units:
            return Claim(CodePath(candidate))
        symbol = model.symbols.get(Qualified(candidate))
        if symbol is not None and symbol.kind is SymbolKind.CLASS:
            return Claim(symbol.unit, Qualified(candidate))
    return None


def _default(model: CodeModel, bases: tuple[str, ...], last: str) -> Claim | None:
    for base in bases or ("",):
        candidate = f"{base}.{last}" if base else last
        if CodePath(candidate) in model.units:
            return Claim(CodePath(candidate))
    for base in bases:
        symbol = model.symbols.get(Qualified(f"{base}.{_camel(last)}"))
        if symbol is not None and symbol.kind is SymbolKind.CLASS:
            return Claim(symbol.unit, symbol.qualified)
    return None


@deal.ensure(lambda record, model, default_adapter, result: set(result[0].dps) == set(record.frs))  # every FR is a DP
@deal.ensure(lambda record, model, default_adapter, result: set(result[0].unit_owner) <= set(model.units)
             and set(result[0].unit_owner.values()) <= set(record.frs))  # only real units, owned by real DPs
def resolve(record: Record, model: CodeModel, default_adapter: AdapterName | None) -> tuple[Tree, tuple[Finding, ...]]:
    problems: list[Finding] = []
    names = sorted(record.frs, key=lambda n: (n.count("."), n))
    children: dict[FrName, list[FrName]] = {n: [] for n in names}
    for n in names:
        if (p := parent(n)) in children:
            children[p].append(n)
    claims: dict[FrName, tuple[Claim, ...]] = {}
    bases: dict[FrName, tuple[str, ...]] = {}
    other_adapters: dict[str, list[FrName]] = {}
    for name in names:
        p = parent(name)
        inherited = bases.get(p, ()) if p is not None else ()
        placement = record.placements.get(name)
        found: list[Claim] = []
        if placement is not None:
            for unit in placement.units:
                adapter = unit.value.adapter_or(default_adapter)
                if adapter not in model.adapters:
                    other_adapters.setdefault(adapter, []).append(name)
                    continue
                claim = _claim(model, inherited, unit.value.path)
                if claim is None:
                    problems.append(finding(Result.BREAKS, PLACEMENT, name, unit.span,
                                            f'no module, package or class "{unit.value.path}" in the code'))
                else:
                    found.append(claim)
        else:
            claim = _default(model, inherited, name.rpartition(".")[2])
            if claim is not None:
                found.append(claim)
        claims[name] = tuple(found)
        own = tuple(c.unit if c.type is None else c.type for c in found)
        bases[name] = own if own else inherited

    for adapter, dps in sorted(other_adapters.items()):
        problems.append(finding(Result.QUESTION, PLACEMENT, adapter, None,
                                f"{len(dps)} DPs name {adapter} code, which waits for the {adapter} adapter: "
                                + ", ".join(sorted(set(dps)))))

    levels: dict[FrName, Level | None] = {}
    for name in reversed(names):  # children first
        if "." not in name:
            levels[name] = Level.SYSTEM
        elif claims[name]:
            levels[name] = Level.STRUCTURE if any(c.type for c in claims[name]) else Level.COMPONENT
        else:
            child_levels = [levels[c] for c in children[name] if levels.get(c) is not None]
            levels[name] = min(child_levels) if child_levels else None
    for name in names:
        p = parent(name)
        if p in levels and levels[name] is not None and levels[p] is not None and levels[name] < levels[p]:
            problems.append(finding(Result.BREAKS, LEVELS, name, record.frs[name].span,
                                    f"a {levels[name].name.lower()} cannot sit inside a {levels[p].name.lower()}"))
        if levels[name] is None:
            problems.append(finding(Result.TODO, COVERAGE, name, record.frs[name].span,
                                    "no code yet: write the module, package or class this DP is"))

    unit_claims: dict[CodePath, list[FrName]] = {}
    type_owner: dict[Qualified, FrName] = {}
    for name, found in claims.items():
        for c in found:
            if c.type is None:
                unit_claims.setdefault(c.unit, []).append(name)
            else:
                type_owner[c.type] = name
    for unit, owners in sorted(unit_claims.items()):
        if len(owners) > 1:
            span = record.placements[owners[1]].span if owners[1] in record.placements else record.frs[owners[1]].span
            problems.append(finding(Result.BREAKS, COVERAGE, unit, span,
                                    f"{unit} is claimed by both {owners[0]} and {owners[1]}"))
    unit_owner: dict[CodePath, FrName] = {}
    for unit in model.units:
        parts = unit.split(".")
        for i in range(len(parts), 0, -1):
            owners = unit_claims.get(CodePath(".".join(parts[:i])))
            if owners:
                unit_owner[unit] = owners[0]
                break
    for unit in sorted(set(model.units) - set(unit_owner)):
        u = model.units[unit]
        if any(other.startswith(unit + ".") and other in unit_owner for other in model.units) and u.size == 0:
            continue  # a folder whose contents all belong somewhere has nothing of its own to cover
        problems.append(finding(Result.BREAKS, COVERAGE, unit, Span(u.span.path, 1, 1),
                                f"{unit} belongs to no design parameter: give it an FR, or place it in physical.yaml"))

    dps = {n: Dp(n, parent(n) if parent(n) in record.frs else None, tuple(children[n]), claims[n], levels[n])
           for n in names}
    return Tree(dps, unit_owner, type_owner), tuple(problems)
