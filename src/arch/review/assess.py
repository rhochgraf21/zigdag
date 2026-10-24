"""How risky each changed file is, and what evidence each touched criterion has.

Realizes arch.review.assess. Shared by the pull-request summary and the step-by-step review, so both
judge a change the same way.

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

from arch.change.diff import DesignDiff
from arch.check.engine import Report
from arch.model.graph import Graph
from arch.model.ids import ComponentId, Text, is_within, split_criterion
from arch.model.schema import Design, Status
from arch.realize.facts import Compatibility, Facts, FileChange, FileDiff, LineNo, PortChange, Role
from arch.realize.history import History
from arch.realize.mapping import map_units

RiskScore = NewType("RiskScore", int)
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
    diffs: tuple[FileDiff, ...] = ()  # the actual changes, for reviewing code


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


def criteria_evidence(design_diff: DesignDiff, facts: Facts) -> tuple[CriterionEvidence, ...]:
    """Evidence for every criterion the change added or reworded."""
    return _criteria(design_diff, facts)


def file_risks(inp: ReviewInput, after: Graph, ports: tuple[PortChange, ...]) -> tuple[FileRisk, ...]:
    """Each changed file's risk score, with the reasons behind it."""
    return tuple(_risks(inp, after, ports))


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
