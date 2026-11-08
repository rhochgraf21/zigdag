"""Working out the data model (DESIGN2 §2.4) from the code model and the DP tree: the recorded structures, their
fields and representations, what each contains and refers to, and which code creates, reads and updates each.

Nothing here is written in the record. A structure is a DP whose code is a type; everything else is read from code.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

from zigdag.core.code import (
    AccessKind,
    CodeModel,
    Field,
    Place,
    Qualified,
    Symbol,
    SymbolKind,
    TestId,
    TypeExpr,
    TypeKind,
    UnitKind,
    Use,
)
from zigdag.core.relate import Relations
from zigdag.core.resolve import Tree
from zigdag.core.findings import Span
from zigdag.core.names import AdapterName, FrName
from zigdag.core.texts import Word


class Cardinality(enum.Enum):
    ONE = "one"
    OPTIONAL = "optional"
    MANY = "many"


class RelationKind(enum.Enum):
    CONTAINS = "contains"
    REFERS_TO = "refers-to"


_MAPPINGS = frozenset({"builtins.dict", "typing.Dict", "typing.Mapping", "typing.MutableMapping",
                       "collections.abc.Mapping", "collections.abc.MutableMapping", "collections.defaultdict",
                       "collections.OrderedDict", "typing.DefaultDict", "typing.OrderedDict"})


def shape(t: TypeExpr | None) -> tuple[Qualified | None, Cardinality]:
    """The one named type a field holds, and how many: `B`, `B | None`, `list[B]`; for a mapping, its values."""
    if t is None:
        return None, Cardinality.ONE
    if t.kind is TypeKind.REF and not t.args:
        return t.name, Cardinality.ONE
    if t.kind is TypeKind.UNION:
        others = [a for a in t.args if a.kind is not TypeKind.NONE]
        if len(others) != 1:
            return None, Cardinality.ONE
        name, card = shape(others[0])
        return name, Cardinality.OPTIONAL if card is Cardinality.ONE else card
    if t.kind is TypeKind.CONTAINER and t.args:
        held = t.args[-1] if t.name in _MAPPINGS else t.args[0]
        return shape(held)[0], Cardinality.MANY
    return None, Cardinality.ONE


def choices(model: CodeModel, t: TypeExpr | None) -> tuple[Word, ...] | None:
    """The values a field can hold when it is an enumeration or a literal, looking through `| None`."""
    if t is None:
        return None
    if t.kind is TypeKind.LITERAL:
        return t.values
    if t.kind is TypeKind.UNION:
        others = [a for a in t.args if a.kind is not TypeKind.NONE]
        return choices(model, others[0]) if len(others) == 1 else None
    symbol = model.symbols.get(t.name) if t.kind is TypeKind.REF and t.name else None
    return symbol.members if symbol is not None and symbol.members else None


def is_flag(t: TypeExpr | None) -> bool:
    """A yes-or-no field, looking through `| None`."""
    if t is None:
        return False
    if t.kind is TypeKind.UNION:
        others = [a for a in t.args if a.kind is not TypeKind.NONE]
        return len(others) == 1 and is_flag(others[0])
    return t.kind is TypeKind.BOOL


@dataclass(frozen=True)
class Structure:
    """A recorded structure: a DP whose code is a type, with one representation per adapter."""

    dp: FrName
    representations: Mapping[AdapterName, Symbol]
    owner: FrName | None  # the component whose code defines it: only it may change the structure
    stored: bool  # it is stored data, such as a table, rather than a type in running code
    span: Span

    @property
    def primary(self) -> Symbol:
        """The representation its relationships are read from: the first adapter's, in name order."""
        return self.representations[min(self.representations)]

    @property
    def fields(self) -> tuple[Field, ...]:
        return self.primary.fields

    @property
    def key(self) -> Field | None:
        return next((f for f in self.fields if f.key), None)

    @property
    def name(self) -> Word:
        """The words a statement uses for it: the last part of its DP's name."""
        return self.dp.rpartition(".")[2].replace("_", " ")


@dataclass(frozen=True)
class Relation:
    """A field of one structure that contains, or refers to, another."""

    source: FrName
    field: Field
    kind: RelationKind
    target: FrName | None  # None: the target is not a recorded structure
    target_type: Qualified  # the type the field names: the structure itself, or its identity type
    cardinality: Cardinality


@dataclass(frozen=True)
class DataAccess:
    """A design parameter's code creating, reading or changing a structure."""

    dp: FrName  # whose code does it
    place: Place
    structure: FrName
    field: str | None
    kind: AccessKind
    in_place: bool
    span: Span
    seen: TestId | None  # seen while this test ran; None when read from the code


@dataclass(frozen=True)
class ValueUse:
    """A value given to a release point or an effect, with the named type it was worked out to have."""

    use: Use
    type: Qualified | None
    dp: FrName | None
    unknown: bool  # its type cannot be worked out, though it may be the project's own: a protected value could hide


@dataclass(frozen=True)
class DataModel:
    structures: Mapping[FrName, Structure]
    by_type: Mapping[Qualified, FrName]  # each representation's type -> its structure
    relations: tuple[Relation, ...]
    accesses: tuple[DataAccess, ...]
    uses: tuple[ValueUse, ...]
    identities: Mapping[Qualified, Qualified]  # an identity type -> the class whose key it is

    def structure_of(self, type_name: Qualified | None) -> Structure | None:
        dp = self.by_type.get(type_name) if type_name else None
        return self.structures[dp] if dp is not None else None

    def named(self, words: Word) -> list[Structure]:
        """The structures a statement can mean by these words: the last part of the DP's name."""
        return [s for _, s in sorted(self.structures.items()) if s.name == words]

    def holding(self, types: frozenset[Qualified]) -> frozenset[Qualified]:
        """The types given, and the type of every structure that holds one of them in a field, however deep."""
        out = set(types)
        changed = True
        while changed:
            changed = False
            for s in self.structures.values():
                mine = {rep.qualified for rep in s.representations.values()}
                if not mine <= out and any(shape(f.type)[0] in out for f in s.fields):
                    out |= mine
                    changed = True
        return frozenset(out)


def work_out(model: CodeModel, tree: Tree, relations: Relations) -> DataModel:
    structures: dict[FrName, Structure] = {}
    by_type: dict[Qualified, FrName] = {}
    for type_name, dp in sorted(tree.type_owner.items()):
        symbol = model.symbols.get(type_name)
        if symbol is None or symbol.kind is not SymbolKind.CLASS:
            continue
        unit = model.units.get(symbol.unit)
        adapter = unit.adapter if unit is not None else None
        if adapter is None:
            continue
        by_type[type_name] = dp
        current = structures.get(dp)
        reps = {**(current.representations if current else {}), adapter: symbol}
        stored = (current.stored if current else False) or unit.kind is UnitKind.TABLE
        structures[dp] = Structure(dp, reps, tree.owner(symbol.unit), stored, symbol.span)

    identities: dict[Qualified, Qualified] = {}
    for symbol in model.symbols.values():
        if symbol.kind is SymbolKind.CLASS:
            key = next((f for f in symbol.fields if f.key), None)
            named = key.type.named if key is not None and key.type is not None else None
            if named is not None and named in model.symbols:  # only a project-defined type tells references apart
                identities.setdefault(named, symbol.qualified)

    found_relations: list[Relation] = []
    for dp, s in sorted(structures.items()):
        for f in s.fields:
            held, card = shape(f.type)
            if held is None or f.key:
                continue
            if held in by_type:
                found_relations.append(Relation(dp, f, RelationKind.CONTAINS, by_type[held], held, card))
            elif held in identities and identities[held] not in {r.qualified for r in s.representations.values()}:
                owner = by_type.get(identities[held])
                found_relations.append(Relation(dp, f, RelationKind.REFERS_TO, owner, identities[held], card))

    accesses: list[DataAccess] = []
    for c in model.calls:
        dp = by_type.get(c.callee)
        who = relations.dp_of(c.caller)
        if dp is not None and who is not None:
            accesses.append(DataAccess(who, c.caller, dp, None, AccessKind.CREATES, False, c.span, c.seen))
    for a in model.accesses:
        type_name = model.type_of(a.value)
        structure = structures.get(by_type.get(type_name)) if type_name else None
        who = relations.dp_of(a.at)
        if structure is None or who is None:
            continue
        if a.field is not None and a.kind is AccessKind.READS and structure.primary.field(a.field) is None:
            continue  # a method or a class attribute, not a field
        accesses.append(DataAccess(who, a.at, structure.dp, a.field, a.kind, a.in_place, a.span, a.seen))

    uses = []
    for u in model.uses:
        type_name = model.type_of(u.value) if u.value is not None else None
        # a value from outside the project, such as a library call's result, cannot be a project type
        unknown = u.value is None or (type_name is None and model.unit_of(u.value.root) is not None)
        uses.append(ValueUse(u, type_name, relations.dp_of(u.at), unknown))
    return DataModel(structures, by_type, tuple(found_relations), tuple(accesses), tuple(uses), identities)
