"""Draft a decomposition for code that has no design yet.

Realizes arch.guide.infer. One draft component per package and module; uses equal to the imports the
code really has, with exports added exactly where visibility requires them, so the first check finds
no boundary errors. Import cycles are proposed as accepted couplings, each with a decision entry
asking for review. Adoption starts green and then tightens.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from arch.change.ops import AddComponent, AddDecision, Operation
from arch.model.ids import (
    ComponentId,
    Ref,
    Text,
    ancestors_of,
    common_ancestor,
    is_within,
    parent_of,
    reference_in,
    short_name,
)
from arch.model.matrix import layer
from arch.model.schema import Status
from arch.realize.facts import Facts, Role, UnitName, UnitShape
from arch.realize.mapping import UnitIndex


@dataclass(frozen=True)
class Inference:
    operations: tuple[Operation, ...]
    components: tuple[ComponentId, ...]
    cycles: tuple[tuple[ComponentId, ...], ...]
    notes: tuple[Text, ...]


def infer(facts: Facts) -> Inference:
    units = {u.name: u for u in facts.units if u.role is Role.SOURCE}
    ids: set[ComponentId] = set()
    for name in units:
        cid = ComponentId(name)
        ids.add(cid)
        ids.update(ancestors_of(cid))

    uses: dict[ComponentId, set[ComponentId]] = defaultdict(set)  # absolute targets
    exports: dict[ComponentId, set[Ref]] = defaultdict(set)
    notes: list[Text] = []
    index = UnitIndex.of(facts)
    for imp in facts.imports:
        if imp.unit not in units or (target := index.target_of(imp)) is None or target not in units:
            continue
        a, b = ComponentId(imp.unit), ComponentId(UnitName(target))
        if is_within(a, b) or is_within(b, a):
            continue
        top = common_ancestor(a, b)
        if top is None:
            notes.append(Text(f"{a} imports {b} from another top-level package; arch references cannot cross roots yet"))
            continue
        b_top = next(x for x in (b, *ancestors_of(b)) if parent_of(x) == top)
        uses[a].add(b)
        for x in ancestors_of(a):
            if x == top:
                break
            uses[x].add(b_top)
        node = b
        while node != b_top:
            parent = parent_of(node)
            exports[parent].add(Ref(short_name(node)))
            node = parent

    cycles = _cycles(ids, uses)
    accepted: dict[ComponentId, list[tuple[Ref, ...]]] = defaultdict(list)
    for group in cycles:
        accepted[parent_of(group[0])].append(tuple(Ref(short_name(c)) for c in group))

    ops: list[Operation] = []
    for cid in sorted(ids, key=lambda c: (c.count("."), c)):
        unit = units.get(UnitName(cid))
        kind = UnitShape.PACKAGE.value if unit is None else unit.shape.value
        refs = tuple(sorted(r for t in uses[cid] if (r := reference_in(ids, cid, t)) is not None))
        ops.append(AddComponent(
            id=cid,
            realizes=(unit.summary if unit and unit.summary else Text("State the requirement this part realizes (inferred from code)")),
            solution=Text(f"The `{cid}` {kind} (inferred from code)"),
            status=Status.DRAFT,
            uses=refs,
            exports=tuple(sorted(exports[cid])),
            accepts_coupling=tuple(sorted(accepted[cid])),
        ))
    for group in cycles:
        names = ", ".join(short_name(c) for c in group)
        ops.append(AddDecision(
            component=parent_of(group[0]),
            title=Text(f"Inferred import cycle among {names}"),
            chose=Text("accept the coupling for now"),
            because=Text("the code imports these from each other, and the inferred design reflects the code so adoption starts green"),
            consequences=Text("review it: break the cycle (move the shared part down a level, or invert a dependency), then remove the acceptance"),
        ))
    return Inference(tuple(ops), tuple(sorted(ids)), cycles, tuple(notes))


def _cycles(ids: set[ComponentId], uses: dict[ComponentId, set[ComponentId]]) -> tuple[tuple[ComponentId, ...], ...]:
    """Coupled sibling sets, as each parent's design matrix would show them."""
    by_parent: dict[ComponentId | None, list[ComponentId]] = defaultdict(list)
    for c in ids:
        by_parent[parent_of(c)].append(c)
    found: list[tuple[ComponentId, ...]] = []
    for parent, kids in by_parent.items():
        if parent is None:
            continue
        deps = {k: [s for s in kids if s != k and any(is_within(t, s) for t in uses[k])] for k in kids}
        found += layer(kids, deps.__getitem__).coupled
    return tuple(sorted(found))
