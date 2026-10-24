"""Results of checks, edits, diffs and plans, presented for people and for agents.

Realizes arch.view.report. Each report wraps the model object it presents and renders it as Markdown
or JSON with the same content; nothing here computes results.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from arch.change import ApplyResult, Outcome
from arch.change.diff import DesignDiff
from arch.check.engine import Finding, Report, Severity
from arch.guide.next import Action
from arch.guide.plan import Plan
from arch.model.ids import Text
from arch.view.render import Count, JsonValue, Markdown, Rendering

__all__ = ["Rendering"]  # re-exported for the catalog

class InfoFindings(enum.Enum):
    LISTED = "listed"
    COUNTED = "counted"  # only the number of info findings is shown


class EditMode(enum.Enum):
    WRITE = "write"
    DRY_RUN = "dry run"


def _finding_line(f: Finding, baselined: bool = False) -> str:
    where = f" ({f.location})" if f.location else ""
    mark = " (baselined)" if baselined else ""
    return f"{f.severity.value:7} {f.rule} {f.subject}: {f.message}{where}{mark}\n        hint: {f.hint}"


def _finding_json(f: Finding) -> JsonValue:
    return {"rule": f.rule, "subject": f.subject, "severity": f.severity.value, "message": f.message,
            "hint": f.hint, "location": str(f.location) if f.location else None}


def _counts(findings: tuple[Finding, ...]) -> str:
    n = {s: sum(1 for f in findings if f.severity is s) for s in Severity}
    return f"{n[Severity.ERROR]} errors, {n[Severity.WARNING]} warnings, {n[Severity.INFO]} info"


@dataclass(frozen=True)
class FindingsReport:
    report: Report
    info: InfoFindings = InfoFindings.COUNTED

    def to_markdown(self) -> Markdown:
        everything = self.info is InfoFindings.LISTED
        shown = [f for f in self.report.findings
                 if everything or (f.severity is not Severity.INFO and not self.report.is_baselined(f))]
        hidden = len(self.report.findings) - len(shown)
        base = len(self.report.baselined)
        tail = (f"; {base} baselined, not blocking" if base else "") + (" (--all to list the rest)" if hidden else "")
        lines = [_finding_line(f, self.report.is_baselined(f)) for f in shown]
        return Markdown("\n".join([*lines, _counts(self.report.findings) + tail]))

    def to_json(self) -> JsonValue:
        return [{**_finding_json(f), "baselined": self.report.is_baselined(f)} for f in self.report.findings]


@dataclass(frozen=True)
class InitReport:
    """What `arch init` drafted from the code."""

    edit: EditReport
    components: Count
    cycles: tuple[tuple[Text, ...], ...]
    baselined: Count
    notes: tuple[Text, ...]

    def to_markdown(self) -> Markdown:
        if self.edit.result.outcome is Outcome.REJECTED:
            return self.edit.to_markdown()
        done = "would draft" if self.edit.mode is EditMode.DRY_RUN else "drafted"
        lines = [f"{done} {self.components} components (status draft) from the code"]
        if self.cycles:
            lines.append(f"{len(self.cycles)} import cycles accepted for review: " + "; ".join(", ".join(c) for c in self.cycles))
        if self.baselined:
            lines.append(f"{self.baselined} remaining errors recorded in design/baseline, so only new ones block")
        lines += [f"note: {n}" for n in self.notes]
        lines += ["next: add needs (`arch add need`), state what each top-level part realizes, then `arch check`"]
        return Markdown("\n".join(lines))

    def to_json(self) -> JsonValue:
        return {"edit": self.edit.to_json(), "components": self.components,
                "cycles": [list(c) for c in self.cycles], "baselined": self.baselined, "notes": list(self.notes)}


@dataclass(frozen=True)
class BaselineReport:
    before: Count
    after: Count
    dropped: Count

    def to_markdown(self) -> Markdown:
        return Markdown(f"baseline: {self.after} findings recorded ({self.dropped} fixed ones dropped, "
                        f"{max(0, self.after - self.before + self.dropped)} newly accepted)")

    def to_json(self) -> JsonValue:
        return {"recorded": self.after, "dropped": self.dropped, "previous": self.before}


@dataclass(frozen=True)
class EditReport:
    result: ApplyResult
    mode: EditMode

    def to_markdown(self) -> Markdown:
        r = self.result
        if r.outcome is Outcome.REJECTED:
            lines = [f"rejected: {r.reason}", "nothing was changed"]
            lines += [_finding_line(f) for f in r.new_findings]
            return Markdown("\n".join(lines + [f"note: {n}" for n in r.notes]))
        verb = "would apply" if self.mode is EditMode.DRY_RUN else "applied"
        lines = [f"{verb} {len(r.operations)} operation{'s' * (len(r.operations) != 1)}:"]
        lines += [f"  - {op.describe()}" for op in r.operations]
        for e in r.design_edits:
            action = "create" if e.before is None else "delete" if e.after is None else "modify"
            lines.append(f"  {action} design/{e.path}")
        for e in r.source_edits:
            lines.append(f"  modify {e.path}")
        if r.new_findings:
            lines.append("new findings (not blocking):")
            lines += ["  " + _finding_line(f) for f in r.new_findings]
        lines += [f"note: {n}" for n in r.notes]
        return Markdown("\n".join(lines))

    def to_json(self) -> JsonValue:
        r = self.result
        return {
            "outcome": r.outcome.value, "mode": self.mode.value, "reason": r.reason,
            "operations": [dict(op.to_json()) for op in r.operations],
            "design_edits": [{"path": e.path, "action": "create" if e.before is None else "delete" if e.after is None else "modify"}
                             for e in r.design_edits],
            "source_edits": [e.path for e in r.source_edits],
            "new_findings": [_finding_json(f) for f in r.new_findings],
            "notes": list(r.notes),
        }


@dataclass(frozen=True)
class DiffReport:
    diff: DesignDiff
    base: Text

    def to_markdown(self) -> Markdown:
        if self.diff.empty:
            return Markdown(f"no design changes since {self.base}")
        return Markdown("\n".join([f"design changes since {self.base}:", *self.diff.lines()]))

    def to_json(self) -> JsonValue:
        return {"base": self.base, "changes": [
            {"kind": c.kind.value, "id": c.ident, "type": c.type.value, "moved_from": c.moved_from,
             "classes": sorted(k.value for k in c.classes),
             "fields": [{"field": f.field, "class": f.change_class.value, "before": f.before, "after": f.after} for f in c.fields]}
            for c in self.diff.changes]}


@dataclass(frozen=True)
class NextReport:
    actions: tuple[Action, ...]

    def to_markdown(self) -> Markdown:
        if not self.actions:
            return Markdown("nothing to do: no open findings in scope")
        lines = []
        for i, a in enumerate(self.actions, 1):
            how = ", ".join(x for x in (f"method: {a.method.value}" if a.method else "",
                                        f"operation: {a.operation.value}" if a.operation else "") if x)
            lines.append(f"{i}. [{a.kind.value}] {a.subject}: {a.what}" + (f"\n   ({how})" if how else ""))
        return Markdown("\n".join(lines))

    def to_json(self) -> JsonValue:
        return [{"kind": a.kind.value, "subject": a.subject, "what": a.what, "rule": a.because.rule,
                 "method": a.method.value if a.method else None, "operation": a.operation.name if a.operation else None}
                for a in self.actions]


@dataclass(frozen=True)
class PlanReport:
    plan: Plan

    def to_markdown(self) -> Markdown:
        p = self.plan
        short = lambda c: c.split(".", 1)[1] if "." in c else c  # noqa: E731
        lines = [f"L{i}  " + " · ".join(short(c) for c in layer) for i, layer in enumerate(p.layering.layers)]
        if p.targets:
            lines.insert(0, f"targets: {', '.join(p.targets)}\nimpacted: {', '.join(p.impacted) or 'nothing else'}\n")
        lines += ["coupled (must change together): " + ", ".join(c) for c in p.layering.coupled]
        return Markdown("\n".join(lines))

    def to_json(self) -> JsonValue:
        p = self.plan
        return {"targets": list(p.targets), "impacted": list(p.impacted),
                "layers": [list(layer) for layer in p.layering.layers], "coupled": [list(c) for c in p.layering.coupled]}
