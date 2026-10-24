"""A change summarised for review, outside in: intent, design, structure, contracts, evidence, then code.

Realizes arch.view.review. A reviewer reads down and stops as soon as something is wrong; nothing below
a wrong intent matters. Code comes last, ranked by risk, with the low-risk files collapsed.

Risk score per changed file (documented so it can be argued with):
  breaking port change +4, port needing review +2, compatible port change +1 (the largest applies)
  new import into another component +2;  new blocking finding in the file or its component +3
  component has failing evidence +2, or no linked evidence +1;  hotspot (most-changed tenth) +1
  belongs to no component +1;  more than 200 lines changed +1
  component verified with passing evidence and no port change: -1;  test files score 0
  high: 4 or more, medium: 2-3, low: 1 or less
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import NewType

from arch.change.diff import ChangeClass, DesignDiff, NodeChangeType, diff
from arch.check.engine import Report
from arch.model.graph import Graph
from arch.model.ids import ComponentId, Text, is_within, split_criterion
from arch.model.schema import Design, Status
from arch.realize.facts import (
    Compatibility,
    Facts,
    FileChange,
    LineNo,
    PortChange,
    Role,
    port_changes,
)
from arch.realize.history import History
from arch.realize.mapping import map_units
from arch.view.diagram import Diagram, DiagramView, changes
from arch.view.render import Count, JsonValue, Markdown

RiskScore = NewType("RiskScore", int)
MAX_CHARACTERS = 65_000  # what a pull-request comment holds
_LARGE_CHANGE = 200


class Risk(enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @staticmethod
    def of(score: RiskScore) -> Risk:
        return Risk.HIGH if score >= 4 else Risk.MEDIUM if score >= 2 else Risk.LOW


@dataclass(frozen=True)
class ReviewInput:
    base: Text
    before: Design
    after: Design
    facts_before: Facts
    facts_after: Facts
    report_before: Report
    report_after: Report
    changed: tuple[FileChange, ...]


@dataclass(frozen=True)
class FileRisk:
    path: Text
    component: ComponentId | None
    score: RiskScore
    reasons: tuple[Text, ...]
    added: LineNo
    removed: LineNo

    @property
    def risk(self) -> Risk:
        return Risk.of(self.score)


@dataclass(frozen=True)
class CriterionEvidence:
    criterion: Text
    verdict: Text  # "passed", "failed", "linked, no report", "no evidence"


@dataclass(frozen=True)
class Review:
    base: Text
    diff: DesignDiff
    diagram: Diagram
    ports: tuple[PortChange, ...]
    new_findings: tuple[Text, ...]
    fixed_findings: Count
    blocking: Count
    criteria: tuple[CriterionEvidence, ...]
    files: tuple[FileRisk, ...]

    @property
    def headline(self) -> Text:
        comps = {c.ident for c in self.diff.changes if c.kind.value == "component"}
        added = sum(f.added for f in self.files)
        removed = sum(f.removed for f in self.files)
        breaking = sum(1 for p in self.ports if p.compatibility is Compatibility.BREAKING)
        high = sum(1 for f in self.files if f.risk is Risk.HIGH)
        return Text(f"{len(comps)} components changed in the design · {len(self.files)} files (+{added} −{removed}) · "
                    f"{breaking} breaking port changes · {len(self.new_findings)} new blocking findings · "
                    f"{high} high-risk files")

    def to_markdown(self) -> Markdown:
        for rows in (None, 40, 15, 5):
            text = self._render(rows, diagram=True)
            if len(text) <= MAX_CHARACTERS:
                return text
        return self._render(5, diagram=False)

    def _render(self, max_rows: int | None, diagram: bool) -> Markdown:
        out = [f"## arch review against `{self.base}`", "", self.headline, ""]

        def layer(n: int, title: str, body: list[str], open_: bool = True) -> None:
            out.extend([f"<details{' open' if open_ else ''}><summary><b>{n}. {title}</b></summary>", "", *(body or ["(no change)"]),
                        "", "</details>", ""])

        layer(1, "Intent: needs, requirements, criteria", self._lines(ChangeClass.INTENT))
        layer(2, "Design: solutions, secrets, decisions, constraints, status",
              self._lines(ChangeClass.DESIGN) + self._lines(ChangeClass.POLICY) + self._lines(ChangeClass.STATUS))
        structure = self._lines(ChangeClass.STRUCTURE)
        if diagram and self.diagram.nodes:
            structure += ["", DiagramView(self.diagram).to_markdown()]
        elif self.diagram.nodes:
            structure += ["", "(diagram left out to fit)"]
        layer(3, "Structure", structure)
        layer(4, "Contracts: ports and their compatibility", self._port_lines())
        layer(5, "Evidence", self._evidence_lines())
        layer(6, "Code, by risk", self._file_lines(max_rows))
        return Markdown("\n".join(out).rstrip() + "\n")

    def _lines(self, cls: ChangeClass) -> list[str]:
        lines = []
        for c in self.diff.of_class(cls):
            if c.type in (NodeChangeType.ADDED, NodeChangeType.REMOVED):
                lines.append(f"- {c.type.value} {c.kind.value} `{c.ident}`")
            elif c.type is NodeChangeType.MOVED and cls is ChangeClass.STRUCTURE:
                lines.append(f"- moved `{c.moved_from}` → `{c.ident}`")
            for f in c.fields:
                if f.change_class is cls:
                    lines.append(f"- `{c.ident}` {f.field}: {_quote(f.before)} → {_quote(f.after)}")
        return lines

    def _port_lines(self) -> list[str]:
        """Breaking and needs-review changes in full; compatible additions and changes as a collapsed list."""
        if not self.ports:
            return []
        order = list(Compatibility)
        ranked = sorted(self.ports, key=lambda p: (order.index(p.compatibility), p.unit, p.symbol))
        attention = [p for p in ranked if p.compatibility is not Compatibility.COMPATIBLE]
        compatible = [p for p in ranked if p.compatibility is Compatibility.COMPATIBLE]

        def row(p: PortChange) -> str:
            detail = f" `{p.before}` → `{p.after}`" if p.type.value == "signature changed" else ""
            return f"| `{p.unit}.{p.symbol}` | {p.type.value}{detail} | {p.compatibility.value} |"

        head = ["| port | change | for callers |", "|---|---|---|"]
        lines = head + [row(p) for p in attention] if attention else ["No breaking or uncertain port changes."]
        if compatible:
            lines += ["", f"<details><summary>{len(compatible)} compatible port changes</summary>", "", *head,
                      *(row(p) for p in compatible), "", "</details>"]
        return lines

    def _evidence_lines(self) -> list[str]:
        lines = [f"- blocking findings now: {self.blocking} ({len(self.new_findings)} new, {self.fixed_findings} fixed)"]
        lines += [f"  - new: {f}" for f in self.new_findings[:20]]
        lines += [f"- `{c.criterion}`: {c.verdict}" for c in self.criteria]
        return lines

    def _file_lines(self, max_rows: int | None) -> list[str]:
        if not self.files:
            return []
        ranked = sorted(self.files, key=lambda f: (-f.score, f.path))
        visible = [f for f in ranked if f.risk is not Risk.LOW]
        low = [f for f in ranked if f.risk is Risk.LOW]

        def row(f: FileRisk) -> str:
            return f"| {f.risk.value} | `{f.path}` | {f.component or '—'} | {'; '.join(f.reasons) or '—'} | +{f.added} −{f.removed} |"

        head = ["| risk | file | component | why | lines |", "|---|---|---|---|---|"]
        shown = visible if max_rows is None else visible[:max_rows]
        lines = head + [row(f) for f in shown] if shown else []
        if max_rows is not None and len(visible) > max_rows:
            lines.append(f"\n…and {len(visible) - max_rows} more medium- or high-risk files")
        if low:
            lows = low if max_rows is None else low[:max_rows]
            lines += ["", f"<details><summary>{len(low)} low-risk files</summary>", "", *head, *(row(f) for f in lows), "",
                      "</details>"]
        return lines

    def to_json(self) -> JsonValue:
        return {
            "base": self.base, "headline": self.headline,
            "design": [{"kind": c.kind.value, "id": c.ident, "type": c.type.value,
                        "classes": sorted(k.value for k in c.classes)} for c in self.diff.changes],
            "ports": [{"unit": p.unit, "symbol": p.symbol, "change": p.type.value, "compatibility": p.compatibility.value}
                      for p in self.ports],
            "evidence": {"blocking": self.blocking, "new": list(self.new_findings), "fixed": self.fixed_findings,
                         "criteria": [{"criterion": c.criterion, "verdict": c.verdict} for c in self.criteria]},
            "files": [{"path": f.path, "component": f.component, "risk": f.risk.value, "score": f.score,
                       "reasons": list(f.reasons), "added": f.added, "removed": f.removed} for f in self.files],
        }


def _quote(text: Text | None) -> str:
    if text is None:
        return "(none)"
    flat = " ".join(text.split())
    return f"“{flat if len(flat) <= 90 else flat[:89] + '…'}”"


def review(inp: ReviewInput) -> Review:
    design_diff = diff(inp.before, inp.after)
    before, after = Graph(inp.before), Graph(inp.after)
    source = {u.name for u in inp.facts_after.units if u.role is Role.SOURCE}
    ports = tuple(p for p in port_changes(inp.facts_before, inp.facts_after) if p.unit in source)

    def blocking(report: Report) -> dict[tuple, Text]:
        return {f.identity: Text(f"{f.rule} {f.subject}: {f.message}") for f in report.blocking}

    now, then = blocking(inp.report_after), blocking(inp.report_before)
    new = tuple(text for key, text in sorted(now.items()) if key not in then)
    fixed = Count(sum(1 for key in then if key not in now))
    return Review(
        base=inp.base,
        diff=design_diff,
        diagram=changes(before, after, design_diff),
        ports=ports,
        new_findings=new,
        fixed_findings=fixed,
        blocking=Count(len(now)),
        criteria=_criteria(design_diff, inp.facts_after),
        files=tuple(_risks(inp, after, ports)),
    )


def _component_dependencies(graph: Graph, facts: Facts) -> dict[ComponentId, set[ComponentId]]:
    """Which components each component's source code imports from (mapped with one design, for comparison)."""
    m = map_units(graph, facts)
    source = {u.name for u in facts.units if u.role is Role.SOURCE}
    out: dict[ComponentId, set[ComponentId]] = {}
    for i in facts.imports:
        a = m.component_of.get(i.unit)
        target = m.target_of(i)
        b = m.component_of.get(target) if target else None
        if i.unit in source and a and b and a != b and not is_within(b, a):
            out.setdefault(a, set()).add(b)
    return out


def _criteria(design_diff: DesignDiff, facts: Facts) -> tuple[CriterionEvidence, ...]:
    """Evidence for every criterion the change added or reworded."""
    touched = sorted({f"{c.ident}#{f.field}" for c in design_diff.changes for f in c.fields
                      if f.field.startswith("AC") and f.after is not None})
    verdicts = {r.test: r.verdict for r in facts.evidence}
    out = []
    for criterion in touched:
        tests = [f"{link.unit}.{link.symbol}" for link in facts.links if link.target == criterion]
        if not tests:
            verdict = "no evidence"
        elif any(t in verdicts and verdicts[t].fails for t in tests):
            verdict = "failed"
        elif all(t in verdicts for t in tests):
            verdict = "passed"
        else:
            verdict = "linked, no report"
        out.append(CriterionEvidence(Text(criterion), Text(verdict)))
    return tuple(out)


def _risks(inp: ReviewInput, after: Graph, ports: tuple[PortChange, ...]) -> list[FileRisk]:
    facts = inp.facts_after
    units = {u.path: u for u in (*inp.facts_before.units, *facts.units)}
    mapping = map_units(after, facts)
    deps_before = _component_dependencies(after, inp.facts_before)
    deps_after = _component_dependencies(after, facts)
    history = History.of(facts)
    churn = sorted(history.churn.values(), reverse=True)
    hot_threshold = churn[max(0, len(churn) // 10 - 1)] if len(churn) >= 10 else None
    weight = {Compatibility.BREAKING: 4, Compatibility.NEEDS_REVIEW: 2, Compatibility.COMPATIBLE: 1}
    new_findings = [f for f in inp.report_after.blocking
                    if f.identity not in {g.identity for g in inp.report_before.blocking}]
    linked: dict[ComponentId, list[str]] = {}
    for link in facts.links:
        linked.setdefault(split_criterion(link.target)[0], []).append(f"{link.unit}.{link.symbol}")
    verdicts = {r.test: r.verdict for r in facts.evidence}
    out = []
    for change in inp.changed:
        unit = units.get(change.path)
        reasons: list[Text] = []
        if unit is not None and unit.role is Role.TEST:
            out.append(FileRisk(Text(change.path), None, RiskScore(0), (Text("test"),), change.added, change.removed))
            continue
        cid = mapping.component_of.get(unit.name) if unit else None
        score = 0
        own_ports = [p for p in ports if unit and p.unit == unit.name]
        if own_ports:
            worst = max(own_ports, key=lambda p: weight[p.compatibility])
            score += weight[worst.compatibility]
            n = sum(1 for p in own_ports if p.compatibility is worst.compatibility)
            reasons.append(Text(f"{len(own_ports)} port changes, all compatible" if worst.compatibility is Compatibility.COMPATIBLE
                                else f"{n} {worst.compatibility.value} of {len(own_ports)} port changes"))
        if unit is not None and cid is not None:
            gained = deps_after.get(cid, set()) - deps_before.get(cid, set())
            mine = {mapping.component_of.get(t) for i in facts.imports if i.unit == unit.name and (t := mapping.target_of(i))}
            gained &= mine
            if gained:
                score += 2
                reasons.append(Text(f"{cid} newly depends on {', '.join(sorted(gained))}"))
        if any((f.location is not None and f.location.path == change.path) or (cid and is_within(ComponentId(f.subject), cid))
               for f in new_findings):
            score += 3
            reasons.append(Text("new blocking finding"))
        if cid is None:
            score += 1
            reasons.append(Text("belongs to no component"))
        else:
            tests = [t for c, ts in linked.items() if is_within(c, cid) or is_within(cid, c) for t in ts]
            if any(t in verdicts and verdicts[t].fails for t in tests):
                score += 2
                reasons.append(Text("failing evidence"))
            elif not tests:
                score += 1
                reasons.append(Text("no linked evidence"))
            elif (after[cid].status is Status.VERIFIED and not own_ports
                  and all(t in verdicts and not verdicts[t].fails for t in tests)):
                score -= 1
                reasons.append(Text("verified, evidence passing"))
        if unit is not None and hot_threshold is not None and history.churn.get(unit.name, 0) >= hot_threshold:
            score += 1
            reasons.append(Text("hotspot"))
        if change.added + change.removed > _LARGE_CHANGE:
            score += 1
            reasons.append(Text("large change"))
        out.append(FileRisk(Text(change.path), cid, RiskScore(score), tuple(reasons), change.added, change.removed))
    return out


__all__ = ["CriterionEvidence", "FileRisk", "Review", "ReviewInput", "Risk", "review"]
