"""Findings that existed before, so only new ones block.

Realizes arch.check.baseline. The baseline is a committed text file, one finding identity per line,
sorted, so concurrent changes rarely conflict. Only an explicit update writes it; at that point
findings that no longer occur drop out, so they cannot silently return.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import NewType

from arch.check.engine import Finding, FindingIdentity, FindingKey, Report, RuleId, Severity, Subject

BaselineText = NewType("BaselineText", str)
_HEADER = "# arch baseline: findings that existed before; `arch baseline` rewrites this file\n"


@dataclass(frozen=True)
class Baseline:
    entries: frozenset[FindingIdentity] = frozenset()

    @staticmethod
    def parse(text: BaselineText) -> Baseline:
        entries = set()
        for line in text.splitlines():
            parts = line.split("\t")
            if line and not line.startswith("#") and len(parts) == 3:
                entries.add((RuleId(parts[0]), Subject(parts[1]), FindingKey(parts[2])))
        return Baseline(frozenset(entries))

    @staticmethod
    def of(findings: Iterable[Finding]) -> Baseline:
        """The blocking findings of a report, to be accepted as the starting point."""
        return Baseline(frozenset(f.identity for f in findings if f.severity is Severity.ERROR))

    def render(self) -> BaselineText:
        lines = sorted("\t".join(_clean(part) for part in entry) for entry in self.entries)
        return BaselineText(_HEADER + "".join(f"{line}\n" for line in lines))

    def covers(self, finding: Finding) -> bool:
        return finding.identity in self.entries

    def stale(self, report: Report) -> frozenset[FindingIdentity]:
        """Entries that no longer occur: fixed since the baseline was written."""
        return self.entries - {f.identity for f in report.findings}


def _clean(part: str) -> str:
    return " ".join(part.split())  # identities never contain tabs or newlines


def applied(report: Report, baseline: Baseline) -> Report:
    """The report with baselined findings marked, plus a nudge when entries have been fixed."""
    covered = frozenset(f.identity for f in report.findings if baseline.covers(f))
    stale = baseline.stale(report)
    nudge = (Finding(Subject("baseline"), RuleId("B001"), FindingKey("stale"), Severity.INFO,
                     f"{len(stale)} baselined finding{'s' * (len(stale) != 1)} no longer occur",
                     "run `arch baseline` to drop them, so they cannot come back unnoticed"),) if stale else ()
    return Report(report.findings + nudge, covered)
