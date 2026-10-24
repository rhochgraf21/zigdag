"""A change summarised for review, outside in: intent, design, structure, contracts, evidence, then code.

Realizes arch.review.summary. A reviewer reads down and stops as soon as something is wrong; nothing below
a wrong intent matters. Code comes last, ranked by risk, with the low-risk files collapsed.

Risk scoring lives in arch.review.assess; this module only presents it.
"""

from __future__ import annotations

from dataclasses import dataclass

from arch.change.diff import ChangeClass, DesignDiff, NodeChangeType, diff
from arch.check.engine import Report
from arch.model.graph import Graph
from arch.model.ids import Text
from arch.realize.facts import (
    Compatibility,
    PortChange,
    Role,
    port_changes,
)
from arch.view.diagram import Diagram, DiagramView, changes
from arch.review.assess import CriterionEvidence, FileRisk, ReviewInput, Risk, criteria_evidence, file_risks
from arch.view.render import Count, JsonValue, Markdown

MAX_CHARACTERS = 65_000  # what a pull-request comment holds


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
        criteria=criteria_evidence(design_diff, inp.facts_after),
        files=file_risks(inp, after, ports),
    )


__all__ = ["CriterionEvidence", "FileRisk", "Review", "ReviewInput", "Risk", "review"]
