"""A change as a deck of review pages, one topic per page, in the order a reviewer can decide them.

Realizes arch.review.items. A reviewer reasons in topics, not nodes: what changed in the needs and
requirements; what the architecture looked like before and after; which constraints changed; which
decisions were made; then the code, one component at a time in build order, each headed by the component
and the requirement it realizes. Every page carries a digest of exactly what it shows, so an approval stays
valid until that page changes, and no longer.
"""

from __future__ import annotations

import enum
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import NewType

from arch.change.diff import ChangeClass, DesignDiff, NodeChangeType, diff
from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import ComponentId, ConstraintId, NeedId, Text, is_within, parent_of, short_name, split_criterion
from arch.model.matrix import layer, matrix_of
from arch.model.schema import Design, Kind
from arch.realize.facts import (
    Compatibility,
    DiffLineKind,
    FileDiff,
    FileShape,
    PortChange,
    Role,
    SourcePath,
    UnitName,
    port_changes,
)
from arch.realize.mapping import map_units
from arch.review.assess import CriterionEvidence, FileRisk, ReviewInput, Risk, criteria_evidence, evidence_of, file_risks
from arch.check.engine import Finding
from arch.check.engine import Kind as FindingKind
from arch.check.ledger import Answer, Response
from arch.review.explain import Doubt, HunkView, Touch, Trace, Tracer
from arch.view.diagram import Diagram, Edge, Mark, Node
from arch.view.render import Count

ItemId = NewType("ItemId", str)
Digest = NewType("Digest", str)

GENERATED = ("uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock")
MAX_PANELS = 6


class Stage(enum.Enum):
    """In review order: each page can be decided without the ones after it."""

    OVERVIEW = "overview"
    INTENT = "needs & requirements"
    ARCHITECTURE = "architecture"
    CONSTRAINTS = "constraints"
    DESIGN = "design decisions"
    FINDINGS = "findings & answers"
    INTERFACES = "interfaces"
    CODE = "code"
    BATCH = "mechanical changes"


class Change(enum.Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    MOVED = "moved"
    UNCHANGED = "unchanged"


class Readiness(enum.Enum):
    READY = "ready"
    NOT_READY = "not ready"


class Mechanical(enum.Enum):
    """Why a file needs no line-by-line reading."""

    GENERATED = "generated or lock file"
    RENAMED = "renamed without changes"
    FORMATTING = "whitespace and formatting only"


# what each page shows


@dataclass(frozen=True)
class Tally:
    label: Text
    count: Count


@dataclass(frozen=True)
class OverviewBody:
    readiness: Readiness
    blocking: Count
    new_findings: tuple[Text, ...]
    failing_tests: tuple[Text, ...]
    tallies: tuple[Tally, ...]
    lines_added: Count
    lines_removed: Count


@dataclass(frozen=True)
class NeedChange:
    need: NeedId
    change: Change
    before: Text | None
    after: Text | None
    stakeholder: Text | None


@dataclass(frozen=True)
class CriterionChange:
    label: Text
    change: Change
    before: Text | None
    after: Text | None
    evidence: Text  # e.g. "passed", "no evidence"


@dataclass(frozen=True)
class RequirementChange:
    component: ComponentId
    change: Change
    moved_from: ComponentId | None
    before: Text | None  # what it realized
    after: Text | None
    serves: tuple[NeedId, ...]
    criteria: tuple[CriterionChange, ...]


@dataclass(frozen=True)
class IntentBody:
    needs: tuple[NeedChange, ...]
    requirements: tuple[RequirementChange, ...]


@dataclass(frozen=True)
class OutsideUse:
    """A use that leaves the drawn part, so it has no box of its own in the diagram."""

    component: ComponentId
    target: ComponentId
    change: Change


@dataclass(frozen=True)
class Panel:
    """One part of the system, before and after: its children and the uses between them."""

    parent: ComponentId | None
    realizes: Text | None
    before: Diagram  # empty when the part is new
    after: Diagram  # empty when the part was removed
    outside: tuple[OutsideUse, ...] = ()  # uses added or removed that point outside the part


@dataclass(frozen=True)
class Rewiring:
    component: ComponentId
    change: Change
    detail: Text  # e.g. "now uses facts; no longer uses history", or "moved from x.y"


@dataclass(frozen=True)
class ArchitectureBody:
    panels: tuple[Panel, ...]
    rewiring: tuple[Rewiring, ...]
    more: Count  # panels left out to keep the page readable


@dataclass(frozen=True)
class ConstraintChange:
    constraint: ConstraintId
    change: Change
    scope_before: tuple[ComponentId, ...]
    scope_after: tuple[ComponentId, ...]
    rule_before: Text | None
    rule_after: Text | None
    statement: Text


@dataclass(frozen=True)
class ConstraintsBody:
    constraints: tuple[ConstraintChange, ...]


@dataclass(frozen=True)
class DesignChange:
    component: ComponentId
    change: Change
    realizes: Text
    solution_before: Text | None
    solution_after: Text | None
    hides_before: Text | None
    hides_after: Text | None
    decisions: tuple[tuple[Text, Change, Text], ...]  # (title, change, text)


@dataclass(frozen=True)
class DesignBody:
    changes: tuple[DesignChange, ...]


@dataclass(frozen=True)
class FindingNote:
    """A finding as it reads now, with how it is answered, if it is."""

    finding: Finding
    answer: Answer | None


@dataclass(frozen=True)
class AnswerNote:
    """An answer given, changed or withdrawn in this change, with the findings it covers."""

    response: Response
    change: Change
    covers: tuple[FindingNote, ...]
    gone: Count  # findings it names that no longer occur


@dataclass(frozen=True)
class FindingsBody:
    raised: tuple[FindingNote, ...]  # findings critics, people and agents recorded in this change
    answers: tuple[AnswerNote, ...]  # answers given, changed or withdrawn in this change
    ideas_waiting: Count  # ideas, from anyone, that still have no answer


@dataclass(frozen=True)
class InterfacesBody:
    ports: tuple[PortChange, ...]
    reexports: tuple[PortChange, ...] = ()  # the same changes, seen through units that re-export the names


@dataclass(frozen=True)
class Hunked:
    """One file's diff, each hunk with the definition it is in, why it changed and what its names mean."""

    diff: FileDiff  # only the hunks shown here
    risk: FileRisk | None
    hunks: tuple[HunkView, ...]


@dataclass(frozen=True)
class Follower:
    """A change in another file that only updates calls to an interface this component changed."""

    component: ComponentId | None
    path: SourcePath
    hunk: HunkView


@dataclass(frozen=True)
class InterfaceNote:
    """An interface the component changed, with the callers updated to match."""

    change: PortChange
    reexported_by: tuple[UnitName, ...]
    callers: tuple[Follower, ...]
    importers: Count = Count(0)  # files outside the component that import the unit defining it


@dataclass(frozen=True)
class Moved:
    """Changes in one of this component's files that are shown on another page, next to their cause."""

    path: SourcePath
    count: Count
    interface: Text
    page: ItemId


@dataclass(frozen=True)
class CodeBody:
    component: ComponentId | None
    realizes: Text | None
    hides: Text | None
    serves: tuple[NeedId, ...]
    constraints: tuple[Text, ...]
    criteria: tuple[CriterionEvidence, ...]
    tests: tuple[Hunked, ...]
    sources: tuple[Hunked, ...]
    interfaces: tuple[InterfaceNote, ...] = ()
    moved: tuple[Moved, ...] = ()

    def views(self) -> tuple[HunkView, ...]:
        """Every hunk the page shows, its own and its callers'."""
        return (*(v for h in (*self.tests, *self.sources) for v in h.hunks),
                *(f.hunk for note in self.interfaces for f in note.callers))


@dataclass(frozen=True)
class BatchBody:
    files: tuple[tuple[Hunked, Mechanical], ...]


ItemBody = (OverviewBody | IntentBody | ArchitectureBody | ConstraintsBody | DesignBody | FindingsBody | InterfacesBody
            | CodeBody | BatchBody)


@dataclass(frozen=True)
class ReviewItem:
    """One review page."""

    id: ItemId
    stage: Stage
    title: Text
    body: ItemBody
    risk: Risk
    blocked_by: tuple[ItemId, ...] = ()

    @property
    def digest(self) -> Digest:
        """Changes exactly when what the page shows changes."""
        return Digest(hashlib.sha256(repr((self.title, self.body)).encode()).hexdigest()[:16])


@dataclass(frozen=True)
class Glossary:
    """What every id means and where it lives, so pages can explain ids on hover and link them."""

    needs: Mapping[NeedId, Text]
    components: Mapping[ComponentId, Text]  # what each must do
    criteria: Mapping[Text, Text]  # "component#ACn" -> its text
    constraints: Mapping[ConstraintId, Text]
    pages: Mapping[ComponentId, ItemId]  # each component's code page, when it has one
    files: Mapping[Text, Text]  # node id -> its design file, relative to the project root
    interfaces: Mapping[Text, Text]  # each changed interface (dotted) -> how it reads now
    interface_pages: Mapping[Text, ItemId]  # the page that shows that change

    @staticmethod
    def of(design: Design, items: tuple[ReviewItem, ...], design_dir: Text) -> Glossary:
        files = {Text(i): Text(f"{design_dir}/{codec.path_of(kind, i)}")
                 for kind, nodes in ((Kind.COMPONENT, design.components), (Kind.NEED, design.needs),
                                     (Kind.CONSTRAINT, design.constraints)) for i in nodes}
        return Glossary(
            needs={k: n.statement for k, n in design.needs.items()},
            components={k: c.realizes for k, c in design.components.items()},
            criteria={Text(cr.id): cr.text for c in design.components.values() for cr in c.criteria},
            constraints={k: c.statement.split(". ")[0] for k, c in design.constraints.items()},
            pages={ComponentId(i.id.removeprefix("code:")): i.id for i in items if i.stage is Stage.CODE},
            files=files,
            interfaces={n.change.dotted: n.change.after or n.change.before or Text("")
                        for i in items if isinstance(i.body, CodeBody) for n in i.body.interfaces},
            interface_pages={n.change.dotted: i.id for i in items if isinstance(i.body, CodeBody) for n in i.body.interfaces},
        )


# building the deck


def _n(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def _listing(*parts: tuple[int, str]) -> str:
    """'4 requirements' or '1 need and 4 requirements', leaving out what did not change."""
    shown = [_n(n, w) for n, w in parts if n]
    return " and ".join(shown) or "nothing"


def build(inp: ReviewInput) -> tuple[ReviewItem, ...]:
    design_diff = diff(inp.design_before, inp.design_after)
    before, after = Graph(inp.design_before), Graph(inp.design_after)
    source = {u.name for u in inp.facts_after.units if u.role is Role.SOURCE}
    ports = tuple(p for p in port_changes(inp.facts_before, inp.facts_after) if p.unit in source)
    risks = {r.path: r for r in file_risks(inp, after, ports)}
    evidence = {c.criterion: c.verdict for c in criteria_evidence(design_diff, inp.design_after, inp.facts_after)}

    pages: list[ReviewItem] = []
    intent = _intent(design_diff, inp.design_before, inp.design_after, evidence)
    if intent.needs or intent.requirements:
        pages.append(ReviewItem(ItemId("intent"), Stage.INTENT,
                                Text(_listing((len(intent.needs), "need"), (len(intent.requirements), "requirement")) + " changed"),
                                intent, Risk.HIGH))
    arch = _architecture(design_diff, before, after)
    if arch.panels:
        pages.append(ReviewItem(ItemId("architecture"), Stage.ARCHITECTURE, _architecture_title(arch), arch, Risk.HIGH))
    constraints = _constraints(design_diff, inp.design_before, inp.design_after)
    if constraints.constraints:
        pages.append(ReviewItem(ItemId("constraints"), Stage.CONSTRAINTS,
                                Text(f"{_n(len(constraints.constraints), 'constraint')} changed"), constraints, Risk.HIGH))
    design = _design(design_diff, inp.design_before, inp.design_after)
    if design.changes:
        pages.append(ReviewItem(ItemId("design"), Stage.DESIGN, Text(f"Design decisions in {_n(len(design.changes), 'component')}"),
                                design, Risk.MEDIUM))
    noticed = _findings(inp)
    if noticed.raised or noticed.answers:
        lenient = any(a.response.answer in (Answer.ACCEPTED, Answer.DECLINED) for a in noticed.answers)
        pages.append(ReviewItem(ItemId("findings"), Stage.FINDINGS, _findings_title(noticed), noticed,
                                Risk.HIGH if lenient else Risk.MEDIUM))
    attention = tuple(p for p in ports if p.compatibility is not Compatibility.COMPATIBLE and p.reexport_of is None)
    if attention:
        breaking = sum(1 for p in attention if p.compatibility is Compatibility.BREAKING)
        shown = {p.dotted for p in attention}
        reexports = tuple(p for p in ports if p.reexport_of in shown)
        pages.append(ReviewItem(ItemId("interfaces"), Stage.INTERFACES,
                                Text(_listing((breaking, "breaking interface change"),
                                              (len(attention) - breaking, "uncertain interface change"))),
                                InterfacesBody(attention, reexports), Risk.HIGH if breaking else Risk.MEDIUM))
    upstream = tuple(p.id for p in pages)
    mapping = map_units(after, inp.facts_after)
    units = (*inp.facts_before.units, *inp.facts_after.units)
    tracer = Tracer(Trace(
        inp.facts_before, inp.facts_after, _touched(design_diff, inp.design_after), ports,
        frozenset(ComponentId(c.ident) for c in design_diff.changes
                  if c.kind is Kind.COMPONENT and c.type is NodeChangeType.ADDED),
        {u.path: mapping.component_of[u.name] for u in units if u.name in mapping.component_of}))
    pages += _code_pages(inp, after, risks, ports, tracer, upstream)
    overview = _overview(inp, design_diff, pages)
    return (overview, *pages)


def _overview(inp: ReviewInput, design_diff: DesignDiff, pages: list[ReviewItem]) -> ReviewItem:
    old = {f.identity for f in inp.report_before.blocking}
    new = tuple(Text(f"{f.rule} {f.subject}: {f.message}") for f in inp.report_after.blocking if f.identity not in old)
    failing = tuple(Text(f"{r.test} ({r.verdict.value})") for r in inp.facts_after.evidence if r.verdict.fails)
    state = Readiness.READY if not new and not failing else Readiness.NOT_READY

    def count(kind: str, *types: NodeChangeType) -> Count:
        return Count(sum(1 for c in design_diff.changes if c.kind.value == kind and c.type in types))

    def tally(n: Count, noun: str, verb: str) -> Tally:
        return Tally(Text(f"{noun if n == 1 else noun + 's'} {verb}"), n)

    views = [v for p in pages if isinstance(p.body, CodeBody) for v in p.body.views()]
    unexplained = Count(sum(1 for v in views if v.unexplained))
    undescribed = Count(len({q.name for v in views for q in v.questions if q.doubt is Doubt.UNDESCRIBED}))
    tallies = (
        tally(unexplained, "change", "with no reason given"),
        tally(undescribed, "new or changed interface name", "without a description"),
        tally(count("need", NodeChangeType.ADDED), "need", "added"),
        tally(count("need", NodeChangeType.CHANGED), "need", "changed"),
        tally(count("component", NodeChangeType.ADDED), "component", "added"),
        tally(count("component", NodeChangeType.REMOVED), "component", "removed"),
        tally(count("component", NodeChangeType.MOVED), "component", "moved"),
        tally(count("constraint", NodeChangeType.ADDED, NodeChangeType.REMOVED, NodeChangeType.CHANGED), "constraint", "changed"),
        tally(Count(len(inp.diffs)), "file", "changed"),
    )
    body = OverviewBody(state, Count(len(inp.report_after.blocking)), new, failing, tallies,
                        Count(sum(d.added for d in inp.diffs)), Count(sum(d.removed for d in inp.diffs)))
    title = Text("Ready for review" if state is Readiness.READY else "Not ready: machine checks report problems")
    return ReviewItem(ItemId("overview"), Stage.OVERVIEW, title, body, Risk.LOW if state is Readiness.READY else Risk.HIGH)


_CHANGE = {NodeChangeType.ADDED: Change.ADDED, NodeChangeType.REMOVED: Change.REMOVED,
           NodeChangeType.CHANGED: Change.CHANGED, NodeChangeType.MOVED: Change.MOVED}


def _intent(design_diff: DesignDiff, before: Design, after: Design, evidence: dict[Text, Text]) -> IntentBody:
    needs = []
    for c in design_diff.changes:
        if c.kind is not Kind.NEED:
            continue
        old, new = before.needs.get(NeedId(c.moved_from or c.ident)), after.needs.get(NeedId(c.ident))
        needs.append(NeedChange(NeedId(c.ident), _CHANGE[c.type], old.statement if old else None,
                                new.statement if new else None, (new or old).stakeholder if (new or old) else None))
    requirements = []
    for c in design_diff.changes:
        if c.kind is not Kind.COMPONENT:
            continue
        intent_fields = [f for f in c.fields if f.change_class is ChangeClass.INTENT]
        if c.type is NodeChangeType.CHANGED and not intent_fields:
            continue
        cid = ComponentId(c.ident)
        old = before.components.get(ComponentId(c.moved_from or c.ident))
        new = after.components.get(cid)
        old_ac = {cr.id.partition("#")[2]: cr.text for cr in old.criteria} if old else {}
        new_ac = {cr.id.partition("#")[2]: cr.text for cr in new.criteria} if new else {}
        criteria = []
        for label in sorted(set(old_ac) | set(new_ac), key=lambda s: int(s[2:]) if s[2:].isdigit() else 0):
            a, b = old_ac.get(label), new_ac.get(label)
            change = Change.ADDED if a is None else Change.REMOVED if b is None else Change.CHANGED if a != b else Change.UNCHANGED
            criteria.append(CriterionChange(Text(label), change, a, b, evidence.get(Text(f"{cid}#{label}"), Text("unchanged"))))
        requirements.append(RequirementChange(
            cid, _CHANGE[c.type], ComponentId(c.moved_from) if c.moved_from else None,
            old.realizes if old else None, new.realizes if new else None,
            (new or old).serves if (new or old) else (), tuple(criteria)))
    return IntentBody(tuple(needs), tuple(requirements))


def _architecture_title(arch: ArchitectureBody) -> Text:
    """Say exactly what happened when it is one thing; otherwise count by kind."""
    if len(arch.rewiring) == 1:
        r = arch.rewiring[0]
        return Text(f"{short_name(r.component)} {r.detail}")
    counts: dict[Change, int] = {}
    for r in arch.rewiring:
        counts[r.change] = counts.get(r.change, 0) + 1
    words = {Change.ADDED: "added", Change.REMOVED: "removed", Change.MOVED: "moved", Change.CHANGED: "use different parts"}
    parts = [f"{n} {words[c]}" for c, n in sorted(counts.items(), key=lambda kv: list(Change).index(kv[0]))]
    return Text(f"{_n(len(arch.rewiring), 'component')} changed: " + ", ".join(parts))


def _children_diagram(g: Graph, parent: ComponentId | None, marks: dict[ComponentId, Mark],
                      edge_marks: dict[tuple[ComponentId, ComponentId], Mark]) -> Diagram:
    if parent is not None and parent not in g:
        return Diagram(Text(""), (), ())
    kids = g.children(parent) if parent is not None else g.roots
    order = matrix_of(g, parent).order if parent is not None else tuple(sorted(kids))
    nodes = tuple(Node(k, short_name(k), g[k].realizes, g[k].status, (), marks.get(k, Mark.UNCHANGED)) for k in order)
    entries = matrix_of(g, parent).entries if parent is not None else frozenset()
    edges = tuple(Edge(a, b, mark=edge_marks.get((a, b), Mark.UNCHANGED)) for a, b in sorted(entries))
    return Diagram(Text(parent or "system"), nodes, edges)


def _architecture(design_diff: DesignDiff, before: Graph, after: Graph) -> ArchitectureBody:
    rewiring: list[Rewiring] = []
    parents: set[ComponentId | None] = set()
    for c in design_diff.changes:
        if c.kind is not Kind.COMPONENT:
            continue
        structural = c.type is not NodeChangeType.CHANGED or ChangeClass.STRUCTURE in c.classes
        if not structural:
            continue
        cid = ComponentId(c.ident)
        parents.add(parent_of(cid))
        if c.moved_from:
            parents.add(parent_of(ComponentId(c.moved_from)))
        if c.type is NodeChangeType.ADDED and after.children(cid):
            parents.add(cid)
        rewiring.append(Rewiring(cid, _CHANGE[c.type], _rewiring_detail(c, before, after)))

    panels = []
    for parent in sorted(parents, key=lambda p: (p.count(".") if p else -1, p or "")):
        old_kids = set(before.children(parent) if parent is None or parent in before else ())
        new_kids = set(after.children(parent) if parent is None or parent in after else ())
        if parent is None:
            old_kids, new_kids = set(before.roots), set(after.roots)
        old_edges = set(matrix_of(before, parent).entries) if parent is not None and parent in before else set()
        new_edges = set(matrix_of(after, parent).entries) if parent is not None and parent in after else set()
        outside = _outside_uses(before, after, old_kids | new_kids, parent)
        rewired = {a for a, _ in old_edges ^ new_edges} | {o.component for o in outside}
        before_marks = {k: Mark.REMOVED for k in old_kids - new_kids} | {k: Mark.CHANGED for k in rewired & old_kids}
        after_marks = {k: Mark.ADDED for k in new_kids - old_kids} | {k: Mark.CHANGED for k in rewired & new_kids}
        old_d = _children_diagram(before, parent, before_marks, {e: Mark.REMOVED for e in old_edges - new_edges})
        new_d = _children_diagram(after, parent, after_marks, {e: Mark.ADDED for e in new_edges - old_edges})
        if not old_d.nodes and not new_d.nodes:
            continue
        g = after if parent is None or parent in after else before
        panels.append(Panel(parent, g[parent].realizes if parent is not None and parent in g else None, old_d, new_d, outside))
    shown = tuple(panels[:MAX_PANELS])
    return ArchitectureBody(shown, tuple(rewiring), Count(len(panels) - len(shown)))


def _outside_uses(before: Graph, after: Graph, kids: set[ComponentId], parent: ComponentId | None) -> tuple[OutsideUse, ...]:
    def outside(g: Graph, c: ComponentId) -> set[ComponentId]:
        return {u for u in g.uses(c) if parent is None or not is_within(u, parent)} if c in g else set()

    out = []
    for c in sorted(kids):
        old, new = outside(before, c), outside(after, c)
        out += [OutsideUse(c, u, Change.ADDED) for u in sorted(new - old)]
        out += [OutsideUse(c, u, Change.REMOVED) for u in sorted(old - new)]
    return tuple(out)


def _rewiring_detail(c, before: Graph, after: Graph) -> Text:
    if c.type is NodeChangeType.MOVED:
        return Text(f"moved from {c.moved_from}")
    if c.type is NodeChangeType.ADDED:
        g = after
        uses = ", ".join(short_name(u) for u in g.uses(ComponentId(c.ident))) if c.ident in g else ""
        return Text(f"new; uses {uses}" if uses else "new")
    if c.type is NodeChangeType.REMOVED:
        return Text("removed")
    cid = ComponentId(c.ident)
    old = {short_name(u) for u in before.uses(cid)} if cid in before else set()
    new = {short_name(u) for u in after.uses(cid)} if cid in after else set()
    parts = []
    if new - old:
        parts.append("now uses " + ", ".join(sorted(new - old)))
    if old - new:
        parts.append("no longer uses " + ", ".join(sorted(old - new)))
    other = [f.field for f in c.fields if f.change_class is ChangeClass.STRUCTURE and f.field != "uses"]
    parts += [f"{f} changed" for f in other]
    return Text("; ".join(parts) or "rewired")


def _constraints(design_diff: DesignDiff, before: Design, after: Design) -> ConstraintsBody:
    out = []
    for c in design_diff.changes:
        if c.kind is not Kind.CONSTRAINT:
            continue
        old = before.constraints.get(ConstraintId(c.moved_from or c.ident))
        new = after.constraints.get(ConstraintId(c.ident))
        out.append(ConstraintChange(
            ConstraintId(c.ident), _CHANGE[c.type],
            old.applies_to if old else (), new.applies_to if new else (),
            old.policy.describe() if old else None, new.policy.describe() if new else None,
            (new or old).statement))
    return ConstraintsBody(tuple(out))


def _design(design_diff: DesignDiff, before: Design, after: Design) -> DesignBody:
    out = []
    for c in design_diff.changes:
        if c.kind is not Kind.COMPONENT:
            continue
        design_fields = [f for f in c.fields if f.change_class is ChangeClass.DESIGN]
        if c.type is NodeChangeType.CHANGED and not design_fields:
            continue
        if c.type is NodeChangeType.REMOVED:
            continue
        cid = ComponentId(c.ident)
        old = before.components.get(ComponentId(c.moved_from or c.ident))
        new = after.components[cid]
        old_dec = {d.title: d.text for d in old.decisions} if old else {}
        decisions = tuple(
            (d.title, Change.ADDED if d.title not in old_dec else Change.CHANGED, d.text)
            for d in new.decisions if old_dec.get(d.title) != d.text)
        if c.type is NodeChangeType.CHANGED and not decisions and not any(
                f.field in ("solution", "hides") for f in design_fields):
            continue
        out.append(DesignChange(cid, _CHANGE[c.type], new.realizes, old.solution if old else None, new.solution,
                                old.hides if old else None, new.hides, decisions))
    return DesignBody(tuple(out))


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


def _findings(inp: ReviewInput) -> FindingsBody:
    """What critics, people and agents raised in this change, and the answers given, changed or withdrawn."""
    before, after = inp.ledger_before, inp.ledger_after
    now = {f.identity: f for f in inp.report_after.findings}
    then = {f.identity: f for f in inp.report_before.findings}
    old_names = {n.name for n in before.noticed}
    raised = tuple(FindingNote(now.get(n.finding.identity, n.finding), _answer(after, n.finding.identity))
                   for n in after.noticed if n.name not in old_names)
    old = {r.name: r for r in before.responses}
    new = {r.name: r for r in after.responses}
    answers = []
    for name in sorted(set(old) | set(new)):
        a, b = old.get(name), new.get(name)
        if a == b:
            continue
        r = b or a
        change = Change.ADDED if a is None else Change.REMOVED if b is None else Change.CHANGED
        covers = tuple(FindingNote(f, _answer(after, i)) for i in r.findings if (f := now.get(i) or then.get(i)) is not None)
        answers.append(AnswerNote(r, change, covers, Count(sum(1 for i in r.findings if i not in now))))
    waiting = sum(1 for n in after.noticed if n.finding.kind is FindingKind.IDEA and after.answer_for(n.finding.identity) is None)
    return FindingsBody(raised, tuple(answers), Count(waiting))


def _findings_title(body: FindingsBody) -> Text:
    parts = ([f"{_n(len(body.answers), 'answer')} given"] if body.answers else []) + \
            ([f"{_n(len(body.raised), 'finding')} raised"] if body.raised else [])
    return Text(" and ".join(parts).capitalize())


def _answer(ledger, identity) -> Answer | None:
    r = ledger.answer_for(identity)
    return r.answer if r is not None else None


def _touched(design_diff: DesignDiff, after: Design) -> dict[Text, Touch]:
    """Criteria the change added or reworded, including every criterion of a component it adds."""
    out: dict[Text, Touch] = {}
    for c in design_diff.changes:
        if c.kind is not Kind.COMPONENT:
            continue
        if c.type is NodeChangeType.ADDED and (new := after.components.get(ComponentId(c.ident))) is not None:
            out.update({Text(cr.id): Touch.ADDED for cr in new.criteria})
        for f in c.fields:
            if f.field.startswith("AC") and f.after is not None:
                out[Text(f"{c.ident}#{f.field}")] = Touch.ADDED if f.before is None else Touch.REWORDED
    return out


def _code_pages(inp: ReviewInput, after: Graph, risks: dict[Text, FileRisk], ports: tuple[PortChange, ...],
                tracer: Tracer, upstream: tuple[ItemId, ...]) -> list[ReviewItem]:
    facts = inp.facts_after
    mapping = map_units(after, facts)
    unit_of = {u.path: u for u in (*inp.facts_before.units, *facts.units)}
    linked: dict[Text, set[ComponentId]] = {}
    for link in facts.links:
        linked.setdefault(Text(link.location.path), set()).add(split_criterion(link.target)[0])
    owner_of = {p.dotted: mapping.component_of.get(p.unit) for p in ports if p.reexport_of is None}

    batch: list[tuple[Hunked, Mechanical]] = []
    sources: dict[ComponentId | None, list[Hunked]] = {}
    tests: dict[ComponentId | None, list[Hunked]] = {}
    callers: dict[Text, list[Follower]] = {}
    moved: dict[ComponentId | None, dict[tuple[SourcePath, Text], int]] = {}
    for d in inp.diffs:
        risk = risks.get(Text(d.path))
        if (why := _mechanical(d)) is not None:
            batch.append((Hunked(d, risk, tracer.plain(d)), why))
            continue
        unit = unit_of.get(d.path)
        is_test = unit is not None and unit.role is Role.TEST
        if is_test:
            owner = (sorted(c for c in linked.get(Text(d.path), set()) if c in after) or [None])[0]
        else:
            owner = mapping.component_of.get(unit.name) if unit else None
        keep: list[HunkView] = []
        for view in tracer.hunks(d):
            cause = owner_of.get(view.follows[0], owner) if view.only_follows else owner
            if cause == owner:
                keep.append(view)
                continue
            callers.setdefault(view.follows[0], []).append(Follower(owner, d.path, view))
            here = moved.setdefault(owner, {})
            here[(d.path, view.follows[0])] = here.get((d.path, view.follows[0]), 0) + 1
        if keep:
            shown = Hunked(replace(d, hunks=tuple(v.hunk for v in keep)), risk, tuple(keep))
            (tests if is_test else sources).setdefault(owner, []).append(shown)

    reexporters: dict[Text, list[UnitName]] = {}
    for p in ports:
        if p.reexport_of is not None:
            reexporters.setdefault(p.reexport_of, []).append(p.unit)
    components = sorted({c for c in (*sources, *tests) if c is not None})
    deps = {c: [o for o in components if o != c and any(is_within(u, o) for u in after.uses(c))] for c in components}
    order = list(layer(components, deps.__getitem__).order)
    out = []
    for cid in [*order, None]:
        mine_src, mine_tests = tuple(sources.get(cid, ())), tuple(tests.get(cid, ()))
        if not mine_src and not mine_tests:
            continue
        notes = tuple(InterfaceNote(p, tuple(sorted(set(reexporters.get(p.dotted, ())))), tuple(callers.get(p.dotted, ())),
                                    Count(len({i.unit for i in facts.imports if mapping.target_of(i) == p.unit
                                               and mapping.component_of.get(i.unit) != cid})))
                      for p in ports if p.reexport_of is None and owner_of.get(p.dotted) == cid)
        away = tuple(Moved(path, Count(n), interface, ItemId(f"code:{owner_of.get(interface) or '(none)'}"))
                     for (path, interface), n in sorted(moved.get(cid, {}).items()))
        if cid is None:
            body = CodeBody(None, None, None, (), (), (), mine_tests, mine_src, notes, away)
            title = Text("Code outside any component")
        else:
            c = after[cid]
            constraints = tuple(Text(f"{k}: {after.design.constraints[k].statement.split('. ')[0]}")
                                for k in after.effective_constraints(cid))
            crit = tuple(replace(evidence_of(Text(cr.id), inp.facts_after), text=cr.text) for cr in c.criteria)
            body = CodeBody(cid, c.realizes, c.hides, after.needs_of(cid), constraints, crit, mine_tests, mine_src, notes, away)
            title = Text(str(cid))
        files = [h for h in (*mine_src, *mine_tests) if h.risk is not None]
        risk = min((h.risk.risk for h in files), key=list(Risk).index, default=Risk.LOW)
        out.append(ReviewItem(ItemId(f"code:{cid or '(none)'}"), Stage.CODE, title, body, risk, upstream))
    if batch:
        out.append(ReviewItem(ItemId("batch"), Stage.BATCH, Text(_n(len(batch), "mechanical change")),
                              BatchBody(tuple(batch)), Risk.LOW, upstream))
    return out


__all__ = [
    "ArchitectureBody", "BatchBody", "Change", "CodeBody", "ConstraintChange", "ConstraintsBody", "CriterionChange",
    "AnswerNote", "DesignBody", "DesignChange", "Digest", "FindingNote", "FindingsBody", "Follower", "Glossary", "InterfaceNote", "Moved", "OutsideUse", "Hunked", "IntentBody", "InterfacesBody", "ItemBody", "ItemId", "Mechanical",
    "NeedChange", "OverviewBody", "Panel", "Readiness", "RequirementChange", "ReviewItem", "Rewiring", "Stage", "Tally",
    "build",
]
