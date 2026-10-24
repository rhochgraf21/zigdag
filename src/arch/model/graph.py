"""Structural queries over a design: hierarchy, references, visibility, constraints, needs.

Realizes arch.model.graph. Hides index structures. Hierarchy comes from dotted ids; references
written inside a component resolve by lexical scope, nearest ancestor first.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from functools import cached_property

import deal

from arch.model.ids import ComponentId, ConstraintId, NeedId, Ref, is_within, parent_of, reference_in, resolve_in
from arch.model.policy import Policy
from arch.model.schema import Component, Design

__all__ = ["Graph", "is_within", "parent_of"]


@dataclass(frozen=True)
class Graph:
    design: Design
    _children: Mapping[ComponentId, tuple[ComponentId, ...]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        kids: dict[ComponentId, list[ComponentId]] = {}
        for cid in self.design.components:
            if (p := parent_of(cid)) is not None:
                kids.setdefault(p, []).append(cid)
        object.__setattr__(self, "_children", {p: tuple(sorted(c)) for p, c in kids.items()})

    # hierarchy

    def __contains__(self, cid: object) -> bool:
        return cid in self.design.components

    def __getitem__(self, cid: ComponentId) -> Component:
        return self.design.components[cid]

    def ids(self) -> tuple[ComponentId, ...]:
        return tuple(sorted(self.design.components))

    def parent(self, cid: ComponentId) -> ComponentId | None:
        return parent_of(cid)

    def children(self, cid: ComponentId) -> tuple[ComponentId, ...]:
        return self._children.get(cid, ())

    def ancestors(self, cid: ComponentId) -> Iterator[ComponentId]:
        p = parent_of(cid)
        while p is not None:
            yield p
            p = parent_of(p)

    @cached_property
    def roots(self) -> tuple[ComponentId, ...]:
        return tuple(c for c in self.ids() if parent_of(c) is None)

    @cached_property
    def leaves(self) -> tuple[ComponentId, ...]:
        return tuple(c for c in self.ids() if not self.children(c))

    # references

    @deal.has()
    def resolve(self, cid: ComponentId, ref: Ref) -> ComponentId | None:
        """Resolve `ref` as written in component `cid`: the nearest ancestor with a descendant path `ref`."""
        return resolve_in(self.design.components, cid, ref)

    def reference(self, cid: ComponentId, target: ComponentId) -> Ref | None:
        """The shortest reference that, written in `cid`, resolves to `target`; the inverse of resolve."""
        return reference_in(self.design.components, cid, target)

    def users_of(self, target: ComponentId) -> tuple[ComponentId, ...]:
        """Components outside `target` whose declared uses name `target` or one of its parts."""
        return tuple(c for c in self.ids() if not is_within(c, target) and any(is_within(u, target) for u in self.uses(c)))

    def uses(self, cid: ComponentId) -> tuple[ComponentId, ...]:
        """Resolved uses of `cid`; unresolved references are reported by arch.check.structure."""
        return tuple(r for ref in self[cid].uses if (r := self.resolve(cid, ref)) is not None)

    def exports(self, cid: ComponentId) -> tuple[ComponentId, ...]:
        return tuple(ComponentId(f"{cid}.{e}") for e in self[cid].exports if f"{cid}.{e}" in self)

    def visible(self, user: ComponentId, target: ComponentId) -> bool:
        """Children of `user`'s ancestors are visible; anything deeper only through `exports`."""
        scope = set(self.ancestors(user))
        node = target
        while (p := parent_of(node)) is not None and p not in scope:
            if node not in self.exports(p):
                return False
            node = p
        return True

    def may_use(self, user: ComponentId, target: ComponentId) -> bool:
        declared = any(is_within(target, u) for u in self.uses(user))
        return declared and self.visible(user, target)

    # inherited properties

    def effective_constraints(self, cid: ComponentId) -> tuple[ConstraintId, ...]:
        scope = {cid, *self.ancestors(cid)}
        return tuple(
            k for k, c in sorted(self.design.constraints.items()) if any(ComponentId(a) in scope for a in c.applies_to)
        )

    def effective_policy(self, cid: ComponentId) -> Policy:
        """The combined policy of every constraint in force for `cid`."""
        return Policy.combine(self.design.constraints[k].policy.for_component(cid) for k in self.effective_constraints(cid))

    def needs_of(self, cid: ComponentId) -> tuple[NeedId, ...]:
        for c in (cid, *self.ancestors(cid)):
            if c in self and self[c].serves:
                return self[c].serves
        return ()
