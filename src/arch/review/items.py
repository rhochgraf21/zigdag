"""A change divided into review items, pulled in the order a reviewer can decide them.

Realizes arch.review.items. One item per decision a reviewer makes: is the change ready; each changed
need, requirement or criterion; each design decision or constraint; the structural change; each breaking
or uncertain port change; each component's code (tests first, then source, in build order); and one
batch for mechanical changes. Every item carries a digest of exactly what it shows, so an approval stays
valid until that item changes, and no longer.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass
from typing import NewType

from arch.change.diff import ChangeClass, DesignDiff, NodeChange, NodeChangeType, diff
from arch.model.graph import Graph
from arch.model.ids import ComponentId, Text, is_within, split_criterion
from arch.model.matrix import layer
from arch.realize.facts import (
    Compatibility,
    DiffLineKind,
    Facts,
    FileDiff,
    FileShape,
    LineNo,
    PortChange,
    Role,
    port_changes,
)
from arch.realize.mapping import map_units
from arch.review.assess import CriterionEvidence, FileRisk, ReviewInput, Risk, criteria_evidence, file_risks
from arch.view.diagram import Diagram, changes
from arch.view.render import Count

ItemId = NewType("ItemId", str)
Digest = NewType("Digest", str)

GENERATED = ("uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock")


class Stage(enum.Enum):
    """In review order: each stage can be decided without the ones after it."""

    READINESS = "readiness"
    INTENT = "intent"
    DESIGN = "design"
    STRUCTURE = "structure"
    CONTRACTS = "contracts"
    CODE = "code"
    BATCH = "batch"


class Readiness(enum.Enum):
    READY = "ready"
    NOT_READY = "not ready"


class Mechanical(enum.Enum):
    """Why a file needs no line-by-line reading."""

    GENERATED = "generated or lock file"
    RENAMED = "renamed without changes"
    FORMATTING = "whitespace and formatting only"


@dataclass(frozen=True)
class ReadinessBody:
    state: Readiness
    blocking: Count
    new_findings: tuple[Text, ...]
    failing_tests: tuple[Text, ...]


@dataclass(frozen=True)
class NodeBody:
    """A changed need, component or constraint, with the fields this stage is about."""

    change: NodeChange
    context: Text | None  # e.g. what the component realizes, for orientation


@dataclass(frozen=True)
class StructureBody:
    diagram: Diagram
    changes: tuple[NodeChange, ...]


@dataclass(frozen=True)
class PortBody:
    change: PortChange


@dataclass(frozen=True)
class Hunked:
    """One file's diff, with each hunk labelled by the definition it falls in."""

    diff: FileDiff
    risk: FileRisk | None
    symbols: tuple[Text | None, ...]  # per hunk


@dataclass(frozen=True)
class CodeBody:
    component: ComponentId | None
    realizes: Text | None
    hides: Text | None
    constraints: tuple[Text, ...]
    criteria: tuple[CriterionEvidence, ...]
    tests: tuple[Hunked, ...]
    sources: tuple[Hunked, ...]


@dataclass(frozen=True)
class BatchBody:
    files: tuple[tuple[Hunked, Mechanical], ...]


ItemBody = ReadinessBody | NodeBody | StructureBody | PortBody | CodeBody | BatchBody


@dataclass(frozen=True)
class ReviewItem:
    id: ItemId
    stage: Stage
    title: Text
    body: ItemBody
    risk: Risk
    blocked_by: tuple[ItemId, ...] = ()

    @property
    def digest(self) -> Digest:
        """Changes exactly when what the item shows changes."""
        return Digest(hashlib.sha256(repr((self.title, self.body)).encode()).hexdigest()[:16])


def build(inp: ReviewInput) -> tuple[ReviewItem, ...]:
    design_diff = diff(inp.before, inp.after)
    before, after = Graph(inp.before), Graph(inp.after)
    source = {u.name for u in inp.facts_after.units if u.role is Role.SOURCE}
    ports = tuple(p for p in port_changes(inp.facts_before, inp.facts_after) if p.unit in source)
    risks = {r.path: r for r in file_risks(inp, after, ports)}
    items: list[ReviewItem] = [_readiness(inp)]
    items += _node_items(design_diff, after, Stage.INTENT, (ChangeClass.INTENT,))
    items += _node_items(design_diff, after, Stage.DESIGN, (ChangeClass.DESIGN, ChangeClass.POLICY, ChangeClass.STATUS))
    structure = _structure(before, after, design_diff)
    items += [structure] if structure else []
    items += [ReviewItem(ItemId(f"port:{p.unit}.{p.symbol}:{p.type.name.lower()}"), Stage.CONTRACTS,
                         Text(f"{p.unit}.{p.symbol}: {p.type.value} ({p.compatibility.value})"), PortBody(p),
                         Risk.HIGH if p.compatibility is Compatibility.BREAKING else Risk.MEDIUM)
              for p in ports if p.compatibility is not Compatibility.COMPATIBLE]
    items += _code_items(inp, after, design_diff, risks, {i.id for i in items})
    return tuple(items)


def _readiness(inp: ReviewInput) -> ReviewItem:
    old = {f.identity for f in inp.report_before.blocking}
    new = tuple(Text(f"{f.rule} {f.subject}: {f.message}") for f in inp.report_after.blocking if f.identity not in old)
    failing = tuple(Text(f"{r.test} ({r.verdict.value})") for r in inp.facts_after.evidence if r.verdict.fails)
    blocking = Count(len(inp.report_after.blocking))
    state = Readiness.READY if not new and not failing else Readiness.NOT_READY
    body = ReadinessBody(state, blocking, new, failing)
    title = Text("Machine checks pass" if state is Readiness.READY else "Not ready: machine checks report problems")
    return ReviewItem(ItemId("readiness"), Stage.READINESS, title, body, Risk.LOW if state is Readiness.READY else Risk.HIGH)


def _node_items(design_diff: DesignDiff, after: Graph, stage: Stage, classes: tuple[ChangeClass, ...]) -> list[ReviewItem]:
    out = []
    for c in design_diff.changes:
        relevant = tuple(f for f in c.fields if f.change_class in classes)
        whole = c.type in (NodeChangeType.ADDED, NodeChangeType.REMOVED) and stage is Stage.INTENT
        if not relevant and not whole:
            continue
        trimmed = NodeChange(c.kind, c.ident, c.type, relevant, c.moved_from)
        context = after[ComponentId(c.ident)].realizes if c.kind.value == "component" and c.ident in after else None
        verb = c.type.value if whole else "changed"
        title = Text(f"{c.kind.value} {c.ident} {verb}" + (f": {', '.join(f.field for f in relevant)}" if relevant else ""))
        risk = Risk.HIGH if stage is Stage.INTENT else Risk.MEDIUM
        out.append(ReviewItem(ItemId(f"{stage.value}:{c.kind.value}:{c.ident}"), stage, title, NodeBody(trimmed, context), risk))
    return out


def _structure(before: Graph, after: Graph, design_diff: DesignDiff) -> ReviewItem | None:
    diagram = changes(before, after, design_diff)
    structural = tuple(c for c in design_diff.changes if c.kind.value == "component"
                       and (c.type is not NodeChangeType.CHANGED or ChangeClass.STRUCTURE in c.classes))
    if not diagram.nodes:
        return None
    return ReviewItem(ItemId("structure"), Stage.STRUCTURE, Text(f"Structure: {len(structural)} components rewired"),
                      StructureBody(diagram, structural), Risk.MEDIUM)


def _mechanical(d: FileDiff) -> Mechanical | None:
    if d.path.rsplit("/", 1)[-1] in GENERATED:
        return Mechanical.GENERATED
    if d.shape is FileShape.RENAMED and not d.hunks:
        return Mechanical.RENAMED
    removed = [" ".join(l.text.split()) for h in d.hunks for l in h.lines if l.kind is DiffLineKind.REMOVED]
    added = [" ".join(l.text.split()) for h in d.hunks for l in h.lines if l.kind is DiffLineKind.ADDED]
    if d.hunks and d.shape is FileShape.MODIFIED and [x for x in removed if x] == [x for x in added if x]:
        return Mechanical.FORMATTING
    return None


def _symbols(d: FileDiff, facts: Facts) -> tuple[Text | None, ...]:
    """The public definition each hunk's first change falls in (nearest definition above it)."""
    defs = sorted((s.location.line, s.name) for s in facts.symbols if s.location.path == d.path)
    out: list[Text | None] = []
    for h in d.hunks:
        first = next((l.new_line or l.old_line for l in h.lines if l.kind is not DiffLineKind.CONTEXT), h.new_start)
        above = [name for line, name in defs if line <= (first or LineNo(0))]
        out.append(Text(above[-1]) if above else None)
    return tuple(out)


def _code_items(inp: ReviewInput, after: Graph, design_diff: DesignDiff, risks: dict[Text, FileRisk],
                existing: set[ItemId]) -> list[ReviewItem]:
    facts = inp.facts_after
    mapping = map_units(after, facts)
    unit_of = {u.path: u for u in (*inp.facts_before.units, *facts.units)}
    linked: dict[Text, set[ComponentId]] = {}
    for link in facts.links:
        linked.setdefault(Text(link.location.path), set()).add(split_criterion(link.target)[0])

    batch: list[tuple[Hunked, Mechanical]] = []
    sources: dict[ComponentId | None, list[Hunked]] = {}
    tests: dict[ComponentId | None, list[Hunked]] = {}
    for d in inp.diffs:
        view = Hunked(d, risks.get(Text(d.path)), _symbols(d, facts))
        if (why := _mechanical(d)) is not None:
            batch.append((view, why))
            continue
        unit = unit_of.get(d.path)
        if unit is not None and unit.role is Role.TEST:
            owners = sorted(c for c in linked.get(Text(d.path), set()) if c in after) or [None]
            tests.setdefault(owners[0], []).append(view)  # with the first component it proves
            continue
        owner = mapping.component_of.get(unit.name) if unit else None
        sources.setdefault(owner, []).append(view)

    components = sorted({c for c in (*sources, *tests) if c is not None})
    deps = {c: [o for o in components if o != c and any(is_within(u, o) for u in after.uses(c))] for c in components}
    order = list(layer(components, deps.__getitem__).order)  # what a component depends on comes first
    evidence = {c.criterion: c for c in criteria_evidence(design_diff, facts)}
    out = []
    for cid in [*order, None]:
        mine_src, mine_tests = tuple(sources.get(cid, ())), tuple(tests.get(cid, ()))
        if not mine_src and not mine_tests:
            continue
        if cid is None:
            body = CodeBody(None, None, None, (), (), mine_tests, mine_src)
            title = Text("Code outside any component")
        else:
            c = after[cid]
            constraints = tuple(Text(f"{k}: {after.design.constraints[k].statement.split('. ')[0]}")
                                for k in after.effective_constraints(cid))
            crit = tuple(evidence.get(Text(cr.id), CriterionEvidence(Text(cr.id), Text("unchanged"))) for cr in c.criteria)
            body = CodeBody(cid, c.realizes, c.hides, constraints, crit, mine_tests, mine_src)
            title = Text(f"Code: {cid}")
        files = [h for h in (*mine_src, *mine_tests) if h.risk is not None]
        risk = min((h.risk.risk for h in files), key=list(Risk).index, default=Risk.LOW)
        blockers = tuple(i for i in (ItemId(f"intent:component:{cid}"), ItemId(f"design:component:{cid}"), ItemId("readiness"))
                         if i in existing) if cid else (ItemId("readiness"),)
        out.append(ReviewItem(ItemId(f"code:{cid or '(none)'}"), Stage.CODE, title, body, risk, blockers))
    if batch:
        out.append(ReviewItem(ItemId("batch:mechanical"), Stage.BATCH,
                              Text(f"{len(batch)} mechanical changes (verify at a glance)"), BatchBody(tuple(batch)), Risk.LOW,
                              (ItemId("readiness"),)))
    return out


__all__ = ["BatchBody", "CodeBody", "Digest", "Hunked", "ItemBody", "ItemId", "Mechanical", "NodeBody", "PortBody",
           "Readiness", "ReadinessBody", "ReviewItem", "Stage", "StructureBody", "build"]
