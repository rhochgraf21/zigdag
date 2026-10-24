"""Design edits as typed operations, each knowing its preconditions and how it changes the design.

Realizes arch.change.ops. Hides operation semantics. Operations act on a Draft (the protocol below,
implemented by arch.change.apply), so they never touch files or transactions themselves.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol, TypeAlias

from arch.model.codec import DecisionDraft, FieldValue, NodeFile
from arch.model.graph import Graph
from arch.model.ids import (
    ComponentId,
    CriterionLabel,
    NeedId,
    Ref,
    Text,
    is_within,
    parent_of,
    short_name,
    split_criterion,
)
from arch.model.schema import DecisionLabel, Design, Kind, Status
from arch.realize.facts import DesignLink

JsonObject: TypeAlias = Mapping[str, object]  # an operation as written by an agent or a script


class Rejected(Exception):
    """An operation's precondition does not hold; nothing in its batch is applied."""


class OpName(enum.Enum):
    ADD_COMPONENT = "add_component"
    ADD_NEED = "add_need"
    ADD_CRITERION = "add_criterion"
    REMOVE_CRITERION = "remove_criterion"
    ADD_DECISION = "add_decision"
    SET = "set"
    LINK = "link"
    UNLINK = "unlink"
    MOVE = "move"
    REMOVE = "remove"


class Relation(enum.Enum):
    """List fields of a component that hold references."""

    USES = "uses"
    EXPORTS = "exports"
    SERVES = "serves"


class Settable(enum.Enum):
    """Fields `set` can change, and the node kind each belongs to."""

    REALIZES = ("realizes", Kind.COMPONENT)
    SOLUTION = ("solution", Kind.COMPONENT)
    HIDES = ("hides", Kind.COMPONENT)
    STATUS = ("status", Kind.COMPONENT)
    STATEMENT = ("statement", Kind.NEED)
    STAKEHOLDER = ("stakeholder", Kind.NEED)
    SIGNAL = ("signal", Kind.NEED)

    def __init__(self, key: str, kind: Kind):
        self.key = key
        self.kind = kind

    @staticmethod
    def named(name: str) -> Settable:
        for s in Settable:
            if s.key == name:
                return s
        raise Rejected(f"'{name}' is not a settable field (settable: {', '.join(s.key for s in Settable)})")


class Removal(enum.Enum):
    REFUSE_IF_USED = "refuse"
    CASCADE = "cascade"


class Draft(Protocol):
    """A working copy of the design that operations change; arch.change.apply provides it."""

    def design(self) -> Design: ...
    def graph(self) -> Graph: ...
    def exists(self, kind: Kind, ident: Text) -> bool: ...
    def file(self, kind: Kind, ident: Text) -> NodeFile: ...
    def put(self, kind: Kind, ident: Text, node: NodeFile) -> None: ...
    def delete(self, kind: Kind, ident: Text) -> None: ...
    def rename(self, kind: Kind, old: Text, new: Text) -> None: ...
    def links(self) -> Sequence[DesignLink]: ...
    def rewrite_link(self, link: DesignLink, target: Text) -> None: ...
    def note(self, text: Text) -> None: ...


class Operation:
    """Base for all operations. Subclasses are frozen dataclasses with a `name`."""

    name: ClassVar[OpName]

    def apply_to(self, draft: Draft) -> None:
        raise NotImplementedError

    def describe(self) -> Text:
        raise NotImplementedError

    def to_json(self) -> JsonObject:
        out: dict[str, object] = {"op": self.name.value}
        for k, v in vars(self).items():
            if isinstance(v, Settable):
                out[k] = v.key
            elif isinstance(v, enum.Enum):
                out[k] = v.value
            elif isinstance(v, tuple):
                out[k] = [list(x) if isinstance(x, tuple) else x for x in v]
            else:
                out[k] = v
        return out


def _component(draft: Draft, cid: ComponentId) -> NodeFile:
    if not draft.exists(Kind.COMPONENT, cid):
        raise Rejected(f"no component '{cid}'")
    return draft.file(Kind.COMPONENT, cid)


@dataclass(frozen=True)
class AddComponent(Operation):
    name: ClassVar[OpName] = OpName.ADD_COMPONENT
    id: ComponentId
    realizes: Text
    solution: Text
    hides: Text | None = None
    status: Status = Status.SPECIFIED
    uses: tuple[Ref, ...] = ()
    exports: tuple[Ref, ...] = ()
    serves: tuple[NeedId, ...] = ()
    criteria: tuple[Text, ...] = ()
    accepts_coupling: tuple[tuple[Ref, ...], ...] = ()

    def apply_to(self, draft: Draft) -> None:
        if draft.exists(Kind.COMPONENT, self.id):
            raise Rejected(f"component '{self.id}' already exists")
        parent = parent_of(self.id)
        if parent is not None and not draft.exists(Kind.COMPONENT, parent):
            raise Rejected(f"its parent '{parent}' does not exist; add it first")
        fields: dict[str, FieldValue] = {
            "realizes": self.realizes, "solution": self.solution, "hides": self.hides,
            "serves": tuple(Ref(n) for n in self.serves), "uses": self.uses, "exports": self.exports,
            "accepts_coupling": self.accepts_coupling, "status": Text(self.status.value),
        }
        node = NodeFile.new(Kind.COMPONENT, fields)
        for text in self.criteria:
            node.add_criterion(text)
        draft.put(Kind.COMPONENT, self.id, node)

    def describe(self) -> Text:
        return Text(f"add component {self.id}")


@dataclass(frozen=True)
class AddNeed(Operation):
    name: ClassVar[OpName] = OpName.ADD_NEED
    id: NeedId
    statement: Text
    stakeholder: Text | None = None
    signal: Text | None = None

    def apply_to(self, draft: Draft) -> None:
        if draft.exists(Kind.NEED, self.id):
            raise Rejected(f"need '{self.id}' already exists")
        node = NodeFile.new(Kind.NEED, {"stakeholder": self.stakeholder, "signal": self.signal}, body=self.statement)
        draft.put(Kind.NEED, self.id, node)

    def describe(self) -> Text:
        return Text(f"add need {self.id}")


@dataclass(frozen=True)
class AddCriterion(Operation):
    name: ClassVar[OpName] = OpName.ADD_CRITERION
    component: ComponentId
    text: Text

    def apply_to(self, draft: Draft) -> None:
        node = _component(draft, self.component)
        label = node.add_criterion(self.text)
        draft.put(Kind.COMPONENT, self.component, node)
        draft.note(Text(f"added {self.component}#{label}"))

    def describe(self) -> Text:
        return Text(f"add an acceptance criterion to {self.component}")


@dataclass(frozen=True)
class RemoveCriterion(Operation):
    name: ClassVar[OpName] = OpName.REMOVE_CRITERION
    component: ComponentId
    label: CriterionLabel

    def apply_to(self, draft: Draft) -> None:
        node = _component(draft, self.component)
        if not node.remove_criterion(self.label):
            raise Rejected(f"{self.component} has no criterion {self.label}")
        draft.put(Kind.COMPONENT, self.component, node)
        if any(l.target == f"{self.component}#{self.label}" for l in draft.links()):
            draft.note(Text(f"code still links to {self.component}#{self.label}; `arch check` will report it"))

    def describe(self) -> Text:
        return Text(f"remove {self.component}#{self.label}")


@dataclass(frozen=True)
class AddDecision(Operation):
    name: ClassVar[OpName] = OpName.ADD_DECISION
    component: ComponentId
    title: Text
    chose: Text
    because: Text
    over: Text | None = None
    consequences: Text | None = None
    previously: Text | None = None
    backed_by: Text | None = None

    def apply_to(self, draft: Draft) -> None:
        node = _component(draft, self.component)
        if any(d.title == self.title for d in draft.design().components[self.component].decisions):
            raise Rejected(f"{self.component} already has a decision titled '{self.title}'")
        lines = [(label, value) for label, value in (
            (DecisionLabel.CHOSE, self.chose), (DecisionLabel.OVER, self.over), (DecisionLabel.BECAUSE, self.because),
            (DecisionLabel.CONSEQUENCES, self.consequences), (DecisionLabel.PREVIOUSLY, self.previously),
            (DecisionLabel.BACKED_BY, self.backed_by)) if value]
        node.add_decision(DecisionDraft(self.title, lines))
        draft.put(Kind.COMPONENT, self.component, node)

    def describe(self) -> Text:
        return Text(f"record decision '{self.title}' on {self.component}")


@dataclass(frozen=True)
class SetField(Operation):
    name: ClassVar[OpName] = OpName.SET
    node: Text  # a component or need id; the field says which kind
    field: Settable
    value: Text | None  # None clears an optional field

    def apply_to(self, draft: Draft) -> None:
        kind = self.field.kind
        if not draft.exists(kind, self.node):
            raise Rejected(f"no {kind.value} '{self.node}' (field '{self.field.key}' belongs to {kind.value}s)")
        if self.field is Settable.STATUS and self.value not in {s.value for s in Status}:
            raise Rejected(f"status must be one of {', '.join(s.value for s in Status)}")
        if self.value is None and self.field in (Settable.REALIZES, Settable.SOLUTION, Settable.STATUS, Settable.STATEMENT):
            raise Rejected(f"'{self.field.key}' is required and cannot be cleared")
        node = draft.file(kind, self.node)
        if self.field is Settable.STATEMENT:
            node.set_body(self.value or Text(""))
        else:
            node.set_field(self.field.key, self.value)
        draft.put(kind, self.node, node)

    def describe(self) -> Text:
        return Text(f"set {self.field.key} of {self.node}")


def _relation_values(design: Design, cid: ComponentId, relation: Relation) -> tuple[Ref, ...]:
    c = design.components[cid]
    return {Relation.USES: c.uses, Relation.EXPORTS: c.exports,
            Relation.SERVES: tuple(Ref(n) for n in c.serves)}[relation]


@dataclass(frozen=True)
class Link(Operation):
    name: ClassVar[OpName] = OpName.LINK
    component: ComponentId
    relation: Relation
    target: Ref

    def apply_to(self, draft: Draft) -> None:
        node = _component(draft, self.component)
        current = _relation_values(draft.design(), self.component, self.relation)
        if self.target in current:
            draft.note(Text(f"{self.component} already lists {self.target} in {self.relation.value}"))
            return
        node.set_field(self.relation.value, (*current, self.target))
        draft.put(Kind.COMPONENT, self.component, node)

    def describe(self) -> Text:
        return Text(f"{self.component} {self.relation.value} += {self.target}")


@dataclass(frozen=True)
class Unlink(Operation):
    name: ClassVar[OpName] = OpName.UNLINK
    component: ComponentId
    relation: Relation
    target: Ref

    def apply_to(self, draft: Draft) -> None:
        node = _component(draft, self.component)
        current = _relation_values(draft.design(), self.component, self.relation)
        if self.target not in current:
            raise Rejected(f"{self.component} does not list {self.target} in {self.relation.value}")
        node.set_field(self.relation.value, tuple(r for r in current if r != self.target))
        draft.put(Kind.COMPONENT, self.component, node)

    def describe(self) -> Text:
        return Text(f"{self.component} {self.relation.value} -= {self.target}")


@dataclass(frozen=True)
class Move(Operation):
    """Rename or re-parent a component and its subtree, rewriting every reference to it."""

    name: ClassVar[OpName] = OpName.MOVE
    component: ComponentId
    to: ComponentId

    def apply_to(self, draft: Draft) -> None:
        before = draft.graph()
        src, dst = self.component, self.to
        if src not in before:
            raise Rejected(f"no component '{src}'")
        if dst in before:
            raise Rejected(f"component '{dst}' already exists")
        if is_within(dst, src):
            raise Rejected("a component cannot move inside itself")
        if (parent := parent_of(dst)) is not None and parent not in before:
            raise Rejected(f"the new parent '{parent}' does not exist")

        def moved(c: ComponentId) -> ComponentId:
            return ComponentId(dst + c[len(src):]) if is_within(c, src) else c

        for c in sorted((c for c in before.ids() if is_within(c, src)), key=len):
            draft.rename(Kind.COMPONENT, c, moved(c))
        after = draft.graph()
        _rewrite_names_in_parents(draft, before, src, dst)
        for old in before.ids():
            new = moved(old)
            refs = before[old].uses
            rewritten = tuple(self._rewrite(before, after, old, new, ref, moved) for ref in refs)
            if rewritten != refs:
                node = draft.file(Kind.COMPONENT, new)
                node.set_field(Relation.USES.value, rewritten)
                draft.put(Kind.COMPONENT, new, node)
        _rewrite_constraints(draft, lambda c: moved(c))
        for link in draft.links():
            comp, label = split_criterion(link.target)
            if is_within(comp, src):
                draft.rewrite_link(link, Text(moved(comp) + (f"#{label}" if label else "")))
        draft.note(Text(f"code for {src} still lives in module {src}; move it to {dst} if ids are module paths"))

    @staticmethod
    def _rewrite(before: Graph, after: Graph, old: ComponentId, new: ComponentId, ref: Ref, moved) -> Ref:
        target = before.resolve(old, ref)
        if target is None:
            return ref  # already dangling; the check reports it
        return after.reference(new, moved(target)) or ref

    def describe(self) -> Text:
        return Text(f"move {self.component} to {self.to}")


def _rewrite_names_in_parents(draft: Draft, before: Graph, src: ComponentId, dst: ComponentId) -> None:
    """Keep the moved component's export and accepted couplings when its parent stays; else drop them."""
    old_parent, new_parent = parent_of(src), parent_of(dst)
    if old_parent is None:
        return
    old_name, new_name = Ref(short_name(src)), Ref(short_name(dst))
    c = before[old_parent]
    same_parent = old_parent == new_parent
    exports = tuple(new_name if same_parent and e == old_name else e for e in c.exports if same_parent or e != old_name)
    groups = tuple(g for g in (tuple(new_name if same_parent and r == old_name else r for r in grp
                                     if same_parent or r != old_name) for grp in c.accepts_coupling) if len(g) >= 2)
    if exports != c.exports or groups != c.accepts_coupling:
        node = draft.file(Kind.COMPONENT, old_parent)
        node.set_field(Relation.EXPORTS.value, exports)
        node.set_field("accepts_coupling", groups)
        draft.put(Kind.COMPONENT, old_parent, node)
    if not same_parent and old_name in c.exports and new_parent is not None:
        Link(new_parent, Relation.EXPORTS, new_name).apply_to(draft)


def _rewrite_constraints(draft: Draft, mapping) -> None:
    for kid, constraint in draft.design().constraints.items():
        scope = tuple(mapping(c) for c in constraint.applies_to)
        if scope != constraint.applies_to:
            node = draft.file(Kind.CONSTRAINT, kid)
            node.set_field("applies_to", tuple(Ref(c) for c in scope if c is not None))
            draft.put(Kind.CONSTRAINT, kid, node)


@dataclass(frozen=True)
class Remove(Operation):
    name: ClassVar[OpName] = OpName.REMOVE
    node: Text
    kind: Kind = Kind.COMPONENT
    mode: Removal = Removal.REFUSE_IF_USED

    def apply_to(self, draft: Draft) -> None:
        if not draft.exists(self.kind, self.node):
            raise Rejected(f"no {self.kind.value} '{self.node}'")
        if self.kind is Kind.NEED:
            self._remove_need(draft, NeedId(self.node))
        elif self.kind is Kind.COMPONENT:
            self._remove_component(draft, ComponentId(self.node))
        else:
            draft.delete(self.kind, self.node)

    def _remove_need(self, draft: Draft, need: NeedId) -> None:
        servers = [c for c, comp in draft.design().components.items() if need in comp.serves]
        if servers and self.mode is Removal.REFUSE_IF_USED:
            raise Rejected(f"'{need}' is served by {', '.join(servers)}; remove with cascade to unlink them")
        for c in servers:
            Unlink(c, Relation.SERVES, Ref(need)).apply_to(draft)
        draft.delete(Kind.NEED, need)

    def _remove_component(self, draft: Draft, cid: ComponentId) -> None:
        g = draft.graph()
        children = g.children(cid)
        users = g.users_of(cid)
        if (children or users) and self.mode is Removal.REFUSE_IF_USED:
            reasons = ([f"children {', '.join(children)}"] if children else []) + ([f"users {', '.join(users)}"] if users else [])
            raise Rejected(f"'{cid}' has {' and '.join(reasons)}; remove with cascade")
        for user in users:
            kept = tuple(r for r in g[user].uses if not ((t := g.resolve(user, r)) and is_within(t, cid)))
            node = draft.file(Kind.COMPONENT, user)
            node.set_field(Relation.USES.value, kept)
            draft.put(Kind.COMPONENT, user, node)
        parent = parent_of(cid)
        if parent is not None:
            name = Ref(short_name(cid))
            p = g[parent]
            node = draft.file(Kind.COMPONENT, parent)
            node.set_field(Relation.EXPORTS.value, tuple(e for e in p.exports if e != name))
            node.set_field("accepts_coupling", tuple(grp for grp in (tuple(r for r in g_ if r != name) for g_ in p.accepts_coupling) if len(grp) >= 2))
            draft.put(Kind.COMPONENT, parent, node)
        _rewrite_constraints(draft, lambda c: None if is_within(c, cid) else c)
        for c in sorted((c for c in g.ids() if is_within(c, cid)), key=len, reverse=True):
            draft.delete(Kind.COMPONENT, c)
        if any(is_within(split_criterion(l.target)[0], cid) for l in draft.links()):
            draft.note(Text(f"code still links to {cid}; `arch check` will report each link"))

    def describe(self) -> Text:
        return Text(f"remove {self.kind.value} {self.node}" + (" (cascade)" if self.mode is Removal.CASCADE else ""))


OPERATIONS: Mapping[OpName, type[Operation]] = {
    op.name: op for op in (AddComponent, AddNeed, AddCriterion, RemoveCriterion, AddDecision, SetField, Link, Unlink, Move, Remove)
}
_ENUM_FIELDS = {"status": Status, "field": Settable, "relation": Relation, "kind": Kind, "mode": Removal}


def from_json(raw: JsonObject) -> Operation:
    """Parse one operation; raises Rejected naming what is wrong."""
    name = raw.get("op")
    try:
        cls = OPERATIONS[OpName(name)]
    except (ValueError, KeyError):
        raise Rejected(f"unknown op '{name}' (known: {', '.join(n.value for n in OpName)})") from None
    fields = {f for f in cls.__dataclass_fields__ if f != "name"}
    unknown = set(raw) - fields - {"op"}
    if unknown:
        raise Rejected(f"{name}: unknown fields {', '.join(sorted(unknown))}")
    args: dict[str, object] = {}
    for key, value in raw.items():
        if key == "op":
            continue
        if key == "field":
            args[key] = Settable.named(str(value))
        elif key in _ENUM_FIELDS:
            try:
                args[key] = _ENUM_FIELDS[key](value)
            except ValueError:
                raise Rejected(f"{name}: invalid {key} '{value}'") from None
        elif key == "accepts_coupling" and isinstance(value, list):
            args[key] = tuple(tuple(Ref(r) for r in group) for group in value if isinstance(group, list))
        elif isinstance(value, list):
            args[key] = tuple(value)
        else:
            args[key] = value
    try:
        return cls(**args)
    except TypeError as e:
        raise Rejected(f"{name}: {e}") from None


__all__ = [
    "AddComponent", "AddCriterion", "AddDecision", "AddNeed", "Draft", "JsonObject", "Link", "Move", "OpName",
    "Operation", "Rejected", "Relation", "Remove", "RemoveCriterion", "Removal", "SetField", "Settable", "Unlink", "from_json",
]
