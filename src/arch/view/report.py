"""Results of checks, edits, diffs and plans, presented for people and for agents.

Realizes arch.view.report. Each report wraps the model object it presents and renders it as Markdown
or JSON with the same content; nothing here computes results.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass

from arch.change import ApplyResult, Outcome
from arch.change.diff import DesignDiff
from arch.check.engine import Finding, Kind, Report, Severity, Source, ref_of
from arch.check.critique import Agreement, Request
from arch.check.ledger import Answer, Ledger
from arch.guide.next import Action
from arch.guide.plan import Plan
from arch.model.ids import DesignPath, Text
from arch.view.render import Count, JsonValue, Markdown, Rendering

__all__ = ["Rendering"]  # re-exported for the catalog

class InfoFindings(enum.Enum):
    LISTED = "listed"
    COUNTED = "counted"  # only the number of info findings is shown


class EditMode(enum.Enum):
    WRITE = "write"
    DRY_RUN = "dry run"


def _finding_line(f: Finding, answered: bool = False) -> str:
    where = f" ({f.location})" if f.location else ""
    mark = " (answered)" if answered else ""
    return f"{f.severity.value:7} {f.rule} {f.subject}: {f.message}{where}{mark}\n        hint: {f.hint}"


def _finding_json(f: Finding) -> JsonValue:
    return {"ref": ref_of(f.identity), "rule": f.rule, "subject": f.subject, "severity": f.severity.value,
            "kind": f.kind.value, "station": f.station.value, "source": f.source.value, "message": f.message,
            "hint": f.hint, "location": str(f.location) if f.location else None, "evidence": f.evidence,
            "found_at": f.found_at.value if f.found_at else None}


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
                 if everything or (f.severity is not Severity.INFO and not self.report.is_answered(f))]
        hidden = len(self.report.findings) - len(shown)
        answered = sum(1 for f in self.report.findings if self.report.is_answered(f))
        tail = (f"; {answered} answered, not blocking" if answered else "") + (" (--all to list the rest)" if hidden else "")
        lines = [_finding_line(f, self.report.is_answered(f)) for f in shown]
        open_ = tuple(f for f in self.report.findings if not self.report.is_answered(f))
        return Markdown("\n".join([*lines, _counts(open_) + tail]))

    def to_json(self) -> JsonValue:
        return [{**_finding_json(f), "answered": self.report.is_answered(f)} for f in self.report.findings]


class Listing(enum.Enum):
    OPEN = "open"  # defects and questions without an answer
    IDEAS = "ideas"  # ideas waiting for an answer
    ESCAPES = "escapes"  # findings noticed later than the station that made them
    ALL = "all"


@dataclass(frozen=True)
class FindingsListing:
    """Findings with their answers, and how often each source's findings were taken up."""

    report: Report
    ledger: Ledger
    listing: Listing = Listing.OPEN

    def rows(self) -> tuple[Finding, ...]:
        def wanted(f: Finding) -> bool:
            match self.listing:
                case Listing.OPEN:  # what someone raised always shows; rules' findings once their station counts
                    return (f.kind is not Kind.IDEA and not self.report.is_answered(f)
                            and (f.source is not Source.RULE or f.severity is not Severity.INFO))
                case Listing.IDEAS:
                    return f.kind is Kind.IDEA and f.source is not Source.RULE and not self.report.is_answered(f)
                case Listing.ESCAPES:
                    return f.escaped
            return True
        return tuple(f for f in self.report.findings if wanted(f))

    def uptake(self) -> dict[Text, tuple[Count, Count]]:
        """Per source of stored findings: (answered as fixed or accepted, answered at all)."""
        out: dict[Text, tuple[int, int]] = {}
        for n in self.ledger.noticed:
            r = self.ledger.answer_for(n.finding.identity)
            if r is None:
                continue
            key = Text(f"{n.finding.source.value} {n.finding.rule}")
            taken, total = out.get(key, (0, 0))
            out[key] = (taken + (r.answer in (Answer.FIXED, Answer.ACCEPTED)), total + 1)
        return {k: (Count(a), Count(b)) for k, (a, b) in sorted(out.items())}

    def to_markdown(self) -> Markdown:
        lines = []
        for f in self.rows():
            r = self.ledger.answer_for(f.identity)
            escaped = f" (made at {f.station.value}, noticed at {f.found_at.value})" if f.escaped else ""
            lines.append(f"{f.kind.value:8} {f.station.value:12} {ref_of(f.identity)}{escaped}\n         {f.message}")
            if f.evidence:
                lines.append(f"         quote: \"{f.evidence}\"")
            if r is not None:
                lines.append(f"         {r.answer.value} by {r.by}: {r.reason.splitlines()[0] if r.reason else ''}")
        if not lines:
            lines.append(f"no {self.listing.value} findings")
        uptake = self.uptake()
        if uptake:
            lines.append("taken up, by source: " + "; ".join(f"{k} {a} of {b}" for k, (a, b) in uptake.items()))
        return Markdown("\n".join(lines))

    def to_json(self) -> JsonValue:
        return {"findings": [{**_finding_json(f), "answer": (r.answer.value if (r := self.ledger.answer_for(f.identity)) else None),
                              "escaped": f.escaped} for f in self.rows()],
                "uptake": {k: {"taken": a, "answered": b} for k, (a, b) in self.uptake().items()}}


@dataclass(frozen=True)
class LedgerWrite:
    """A finding recorded, or an answer given."""

    summary: Text
    path: DesignPath

    def to_markdown(self) -> Markdown:
        return Markdown(f"{self.summary}\n  wrote design/{self.path}")

    def to_json(self) -> JsonValue:
        return {"summary": self.summary, "path": f"design/{self.path}"}


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
            lines.append(f"{len(self.cycles)} import cycles found, to resolve before their parents are specified: "
                         + "; ".join(", ".join(c) for c in self.cycles))
        if self.baselined:
            lines.append(f"{self.baselined} remaining errors accepted in design/responses/baseline.md, so only new ones block")
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


@dataclass(frozen=True)
class CritiqueListing:
    """The nodes whose text an independent critic has not judged since it last changed."""

    waiting: tuple[Text, ...]

    def to_markdown(self) -> Markdown:
        if not self.waiting:
            return Markdown("every node that must be critiqued has been, since it last changed")
        return Markdown("\n".join([
            f"{len(self.waiting)} node{'s' * (len(self.waiting) != 1)} wait for an independent critic: "
            + ", ".join(self.waiting),
            "next: `arch critique --request > request.json`, hand it to a reviewer that did not write the text "
            "and has no other context, then `arch critique --record answer.json`"]))

    def to_json(self) -> JsonValue:
        return {"waiting": list(self.waiting)}


@dataclass(frozen=True)
class CritiqueRequestView:
    """A critic's request: the rubric and the text to judge. Always JSON, for the critic to read."""

    request: Request

    def to_markdown(self) -> Markdown:
        return Markdown(self.request.to_json())

    def to_json(self) -> JsonValue:
        return json.loads(self.request.to_json())


@dataclass(frozen=True)
class CritiqueRecorded:
    """What arch accepted from a critic's answer, and what it refused and why."""

    critic: Text
    reviewed: Count
    recorded: Count
    repeated: Count  # already noticed and still open
    refused: tuple[Text, ...]

    def to_markdown(self) -> Markdown:
        lines = [f"{self.critic} reviewed {self.reviewed}: {self.recorded} findings recorded, "
                 f"{self.repeated} already open, {len(self.refused)} refused"]
        lines += [f"  refused: {r}" for r in self.refused]
        if self.recorded:
            lines.append("next: `arch findings`, then fix each one or answer it with `arch respond`")
        return Markdown("\n".join(lines))

    def to_json(self) -> JsonValue:
        return {"critic": self.critic, "reviewed": self.reviewed, "recorded": self.recorded, "repeated": self.repeated,
                "refused": list(self.refused)}


@dataclass(frozen=True)
class CalibrationReport:
    """How often a critic agreed with each question's own examples."""

    critic: Text
    agreements: tuple[Agreement, ...]

    def to_markdown(self) -> Markdown:
        right = sum(a.right for a in self.agreements)
        asked = sum(a.asked for a in self.agreements)
        lines = [f"{self.critic}: {right} of {asked} examples judged as the rubric expects"]
        lines += [f"  {a.question}: {a.right} of {a.asked}" for a in self.agreements if a.right < a.asked]
        return Markdown("\n".join(lines))

    def to_json(self) -> JsonValue:
        return {"critic": self.critic, "questions": {a.question: {"right": a.right, "asked": a.asked} for a in self.agreements}}
