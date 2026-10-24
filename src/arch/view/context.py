"""The context card: what an actor needs to work on one component, and nothing more.

Realizes arch.view.context. Complete about the component itself; neighbours appear only by their
external spec (what they realize, their port), never their internals. Over budget, sections are
compacted and then dropped in a fixed priority order, and the card says what it left out.
"""

from __future__ import annotations

from dataclasses import dataclass

from arch.check.engine import Report, Severity
from arch.model.graph import Graph, is_within
from arch.model.matrix import matrix_of
from arch.model.ids import ComponentId
from arch.realize.facts import Facts, UnitName
from arch.realize.mapping import UnitMap, map_units

DEFAULT_BUDGET_TOKENS = 4000
CHARS_PER_TOKEN = 4  # estimate; arch has no tokenizer


class UnknownTarget(Exception):
    pass


@dataclass(frozen=True)
class Section:
    title: str
    lines: tuple[str, ...]
    priority: int  # 0 is never dropped; higher numbers go first
    compact: tuple[str, ...] | None = None  # a shorter form tried before dropping


@dataclass(frozen=True)
class Card:
    component: ComponentId
    focus: str | None
    sections: tuple[Section, ...]
    omitted: tuple[str, ...] = ()
    compacted: tuple[str, ...] = ()
    budget_tokens: int = DEFAULT_BUDGET_TOKENS

    def to_text(self) -> str:
        out = [f"# Context: {self.component}"]
        if self.focus:
            out.append(f"Focus: {self.focus}")
        for s in self.sections:
            out += ["", f"## {s.title}", *s.lines]
        notes = []
        if self.compacted:
            notes.append(f"shortened: {', '.join(self.compacted)}")
        if self.omitted:
            notes.append(f"omitted: {', '.join(self.omitted)}")
        if notes:
            out += ["", f"_({'; '.join(notes)}, to fit ~{self.budget_tokens} tokens)_"]
        return "\n".join(out)

    def to_json(self) -> dict[str, object]:
        return {
            "component": self.component,
            "focus": self.focus,
            "sections": {s.title: list(s.lines) for s in self.sections},
            "compacted": list(self.compacted),
            "omitted": list(self.omitted),
            "budget_tokens": self.budget_tokens,
        }

    @property
    def tokens(self) -> int:
        return len(self.to_text()) // CHARS_PER_TOKEN


def context(graph: Graph, facts: Facts, report: Report, target: str, budget: int = DEFAULT_BUDGET_TOKENS) -> Card:
    m = map_units(graph, facts)
    cid, focus = _resolve(graph, facts, m, target)
    sections = _sections(graph, facts, m, report, cid)
    return _fit(Card(cid, focus, sections, budget_tokens=budget))


def _resolve(graph: Graph, facts: Facts, m: UnitMap, target: str) -> tuple[ComponentId, str | None]:
    if target in graph:
        return ComponentId(target), None
    path, _, line_text = target.partition(":")
    line = int(line_text) if line_text.isdigit() else None
    unit = next((u for u in facts.units if u.path == path or u.name == path), None)
    if unit is None:
        raise UnknownTarget(f"'{target}' is neither a component nor a known source file or module")
    cid = m.component_of.get(unit.name)
    if cid is None:
        raise UnknownTarget(f"{unit.path} belongs to no component" + (" (it is a test)" if unit.role.value == "test" else ""))
    focus = f"{unit.path} (module {unit.name})"
    if line is not None:
        above = [s for s in facts.symbols if s.unit == unit.name and s.location.line <= line]
        if above:
            nearest = max(above, key=lambda s: s.location.line)
            focus = f"{unit.path}:{line}, in `{nearest.name}` (nearest public definition above)"
    return cid, focus


def _sections(graph: Graph, facts: Facts, m: UnitMap, report: Report, cid: ComponentId) -> tuple[Section, ...]:
    c = graph[cid]
    design = graph.design
    own_units = [u for u, owner in m.component_of.items() if owner == cid]
    linked: dict[str, list[str]] = {}
    for link in facts.links:
        linked.setdefault(link.target, []).append(f"{link.unit}.{link.symbol}")

    head = [f"**Realizes:** {c.realizes}", f"**Solution:** {c.solution}"]
    if c.hides:
        head.append(f"**Hides:** {c.hides}")
    head.append(f"**Status:** {c.status.value}")
    paths = sorted(u.path for u in facts.units if u.name in own_units)
    head.append(f"**Code:** {', '.join(paths) if paths else 'none yet'}")

    why = [f"- {a}: {graph[a].realizes}" for a in graph.ancestors(cid)]
    why += [f"- need `{n}`: {_first_sentence(design.needs[n].statement)}" for n in graph.needs_of(cid) if n in design.needs]

    criteria = []
    for cr in c.criteria:
        ev = linked.get(cr.id)
        status = f"evidence: {', '.join(sorted(ev))}" if ev else "no evidence yet"
        criteria.append(f"- **{cr.id.partition('#')[2]}** {cr.text}  _({status})_")

    port = _port_lines(graph, facts, m, cid)

    decisions = []
    for d in c.decisions:
        chose = next((l.removeprefix("- Chose:").strip() for l in d.text.splitlines() if l.startswith("- Chose:")), "")
        decisions.append(f"- **{d.title}**: {chose}" if chose else f"- **{d.title}**")

    constraints = [f"- `{k}`: {_first_sentence(design.constraints[k].statement)}" for k in graph.effective_constraints(cid)]

    findings = [
        f"- {f.severity.value} {f.rule}: {f.message}" + (f" ({f.location})" if f.location else "")
        for f in report.findings
        if f.severity is not Severity.INFO and (f.subject == cid or f.subject in own_units)
    ]

    uses_full: list[str] = []
    uses_short: list[str] = []
    for u in graph.uses(cid):
        uses_short.append(f"- `{u}`: {graph[u].realizes}")
        uses_full.append(f"### {u}")
        uses_full.append(graph[u].realizes)
        uses_full += _port_lines(graph, facts, m, u, contracts=False) or ["(no code yet)"]

    kids = matrix_of(graph, cid).order
    children = [f"- `{k.rsplit('.', 1)[1]}` [{graph[k].status.value}]: {graph[k].realizes}" for k in kids]

    used_by = [f"- `{o}`: {graph[o].realizes}" for o in graph.ids() if o != cid and any(is_within(cid, u) for u in graph.uses(o))]

    candidates = [
        Section("Component", tuple(head), 0),
        Section("Why it exists", tuple(why), 1),
        Section("Acceptance criteria", tuple(criteria) or ("(none)",), 1),
        Section("Port", tuple(port) or ("(no public symbols yet)",), 1),
        Section("Decisions", tuple(decisions), 2),
        Section("Constraints in force", tuple(constraints), 2),
        Section("Open findings", tuple(findings), 2),
        Section("May use", tuple(uses_full), 3, compact=tuple(uses_short)),
        Section("Children (realization order)", tuple(children), 4),
        Section("Used by", tuple(used_by), 5),
    ]
    return tuple(s for s in candidates if s.lines)


def _port_lines(graph: Graph, facts: Facts, m: UnitMap, cid: ComponentId, contracts: bool = True) -> list[str]:
    """Public symbols of the units that belong directly to `cid`, plus the children it exports."""
    units = {u for u, owner in m.component_of.items() if owner == cid}
    by_symbol: dict[tuple[UnitName, str], list[str]] = {}
    if contracts:
        for k in facts.contracts:
            if k.unit in units:
                by_symbol.setdefault((k.unit, k.symbol), []).append(f"{k.kind}({k.expression})")
    lines = []
    for s in facts.symbols:
        if s.unit in units:
            lines.append(f"- `{s.signature}`" + (f"  contracts: {', '.join(by_symbol[(s.unit, s.name)])}" if (s.unit, s.name) in by_symbol else ""))
    for e in graph.exports(cid):
        lines.append(f"- exports `{e.rsplit('.', 1)[1]}`: {graph[e].realizes}")
    return lines


def _first_sentence(text: str) -> str:
    flat = " ".join(text.split())
    end = flat.find(". ")
    return flat if end < 0 else flat[: end + 1]


def _fit(card: Card) -> Card:
    """Compact, then drop, the lowest-priority sections until the card fits its budget."""
    sections = list(card.sections)
    omitted: list[str] = []
    compacted: list[str] = []

    def current() -> Card:
        return Card(card.component, card.focus, tuple(sections), tuple(omitted), tuple(compacted), card.budget_tokens)

    for s in sorted((s for s in card.sections if s.priority > 0), key=lambda s: -s.priority):
        if current().tokens <= card.budget_tokens:
            break
        i = sections.index(s)
        if s.compact is not None:
            sections[i] = Section(s.title, s.compact, s.priority)
            compacted.append(s.title)
            if current().tokens <= card.budget_tokens:
                break
        sections.pop(i)
        if s.title in compacted:
            compacted.remove(s.title)
        omitted.append(s.title)
    return current()


__all__ = ["Card", "UnknownTarget", "context"]
