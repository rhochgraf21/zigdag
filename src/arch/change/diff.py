"""The semantic difference between two design states.

Realizes arch.change.diff. Nodes are matched by id; a node that disappears under one id and appears
under another with the same content is a move. Each change is classified, so a reviewer can read
intent first and prose last.
"""

from __future__ import annotations

import enum
from collections.abc import Iterator
from dataclasses import dataclass

from arch.model.ids import FieldName, Text
from arch.model.schema import Component, Constraint, Design, Kind, Need


class ChangeClass(enum.Enum):
    """In review order."""

    INTENT = "intent"  # needs, what components realize, acceptance criteria, what they serve
    DESIGN = "design"  # the chosen solution, its secret, decisions
    STRUCTURE = "structure"  # hierarchy, uses, exports, accepted couplings
    POLICY = "policy"  # constraints
    STATUS = "status"  # maturity
    PROSE = "prose"  # rationale and other text


class NodeChangeType(enum.Enum):
    ADDED = "added"
    REMOVED = "removed"
    MOVED = "moved"
    CHANGED = "changed"


@dataclass(frozen=True)
class FieldChange:
    field: FieldName
    change_class: ChangeClass
    before: Text | None
    after: Text | None


@dataclass(frozen=True)
class NodeChange:
    kind: Kind
    ident: Text
    type: NodeChangeType
    fields: tuple[FieldChange, ...] = ()
    moved_from: Text | None = None

    @property
    def classes(self) -> frozenset[ChangeClass]:
        if self.type in (NodeChangeType.ADDED, NodeChangeType.REMOVED):
            return frozenset({ChangeClass.INTENT if self.kind is not Kind.CONSTRAINT else ChangeClass.POLICY})
        own = {f.change_class for f in self.fields}
        return frozenset(own | ({ChangeClass.STRUCTURE} if self.type is NodeChangeType.MOVED else set()))


@dataclass(frozen=True)
class DesignDiff:
    changes: tuple[NodeChange, ...]

    @property
    def empty(self) -> bool:
        return not self.changes

    def of_class(self, cls: ChangeClass) -> tuple[NodeChange, ...]:
        return tuple(c for c in self.changes if cls in c.classes)

    def lines(self) -> tuple[Text, ...]:
        """A plain description, grouped by class in review order."""
        out: list[Text] = []
        for cls in ChangeClass:
            group = [c for c in self.changes if cls in c.classes]
            if not group:
                continue
            out.append(Text(f"{cls.value}:"))
            for c in group:
                head = f"  {c.type.value} {c.kind.value} {c.ident}" + (f" (from {c.moved_from})" if c.moved_from else "")
                out.append(Text(head))
                for f in c.fields:
                    if f.change_class is cls:
                        out.append(Text(f"    {f.field}: {_short(f.before)} -> {_short(f.after)}"))
        return tuple(out)


def _short(text: Text | None, width: int = 70) -> str:
    if text is None:
        return "(none)"
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def diff(before: Design, after: Design) -> DesignDiff:
    changes: list[NodeChange] = []
    changes += _diff_kind(Kind.NEED, before.needs, after.needs, _need_fields)
    changes += _diff_kind(Kind.COMPONENT, before.components, after.components, _component_fields)
    changes += _diff_kind(Kind.CONSTRAINT, before.constraints, after.constraints, _constraint_fields)
    return DesignDiff(tuple(changes))


def _diff_kind(kind: Kind, old: dict, new: dict, fields) -> Iterator[NodeChange]:
    removed = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    moves: dict[str, str] = {}
    for a in added:
        match = next((r for r in removed if r not in moves.values() and _signature(kind, old[r]) == _signature(kind, new[a])), None)
        if match is not None:
            moves[a] = match
    for ident in sorted(set(old) & set(new)):
        changed = tuple(fields(old[ident], new[ident]))
        if changed:
            yield NodeChange(kind, Text(ident), NodeChangeType.CHANGED, changed)
    for a, r in sorted(moves.items()):
        yield NodeChange(kind, Text(a), NodeChangeType.MOVED, tuple(fields(old[r], new[a])), Text(r))
    for r in removed:
        if r not in moves.values():
            yield NodeChange(kind, Text(r), NodeChangeType.REMOVED)
    for a in added:
        if a not in moves:
            yield NodeChange(kind, Text(a), NodeChangeType.ADDED)


def _signature(kind: Kind, node) -> tuple:
    """What must stay equal for a removal plus an addition to count as a move."""
    if kind is Kind.COMPONENT:
        return (node.realizes, node.solution)
    if kind is Kind.NEED:
        return (node.statement,)
    return (node.statement, node.policy)


def _text(value) -> Text | None:
    if value is None:
        return None
    if isinstance(value, tuple):
        return Text(", ".join(" + ".join(v) if isinstance(v, tuple) else str(v) for v in value))
    return Text(str(value.value) if isinstance(value, enum.Enum) else str(value))


def _compare(name: str, cls: ChangeClass, a, b) -> Iterator[FieldChange]:
    if a != b:
        yield FieldChange(FieldName(name), cls, _text(a), _text(b))


def _component_fields(a: Component, b: Component) -> Iterator[FieldChange]:
    yield from _compare("realizes", ChangeClass.INTENT, a.realizes, b.realizes)
    yield from _compare("serves", ChangeClass.INTENT, a.serves, b.serves)
    yield from _compare("solution", ChangeClass.DESIGN, a.solution, b.solution)
    yield from _compare("hides", ChangeClass.DESIGN, a.hides, b.hides)
    yield from _compare("uses", ChangeClass.STRUCTURE, a.uses, b.uses)
    yield from _compare("exports", ChangeClass.STRUCTURE, a.exports, b.exports)
    yield from _compare("accepts_coupling", ChangeClass.STRUCTURE, a.accepts_coupling, b.accepts_coupling)
    yield from _compare("status", ChangeClass.STATUS, a.status, b.status)
    crit_a = {c.id.partition("#")[2]: c.text for c in a.criteria}
    crit_b = {c.id.partition("#")[2]: c.text for c in b.criteria}
    for label in sorted(set(crit_a) | set(crit_b), key=lambda s: int(s[2:]) if s[2:].isdigit() else 0):
        yield from _compare(label, ChangeClass.INTENT, crit_a.get(label), crit_b.get(label))
    dec_a = {d.title: d.text for d in a.decisions}
    dec_b = {d.title: d.text for d in b.decisions}
    for title in sorted(set(dec_a) | set(dec_b)):
        yield from _compare(f"decision '{title}'", ChangeClass.DESIGN, dec_a.get(title), dec_b.get(title))


def _need_fields(a: Need, b: Need) -> Iterator[FieldChange]:
    yield from _compare("statement", ChangeClass.INTENT, a.statement, b.statement)
    yield from _compare("stakeholder", ChangeClass.INTENT, a.stakeholder, b.stakeholder)
    yield from _compare("signal", ChangeClass.INTENT, a.signal, b.signal)


def _constraint_fields(a: Constraint, b: Constraint) -> Iterator[FieldChange]:
    yield from _compare("applies_to", ChangeClass.POLICY, a.applies_to, b.applies_to)
    if a.policy != b.policy:
        yield FieldChange(FieldName("rule"), ChangeClass.POLICY, Text("(previous rule)"), Text("(new rule)"))
    yield from _compare("statement", ChangeClass.PROSE, a.statement, b.statement)
