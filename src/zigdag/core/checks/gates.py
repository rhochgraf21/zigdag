"""Workflow gates (DESIGN2 §7.6): the steps a change must pass, read from the log against the entries it changed.

Gates need a change, meaning a base to compare with, except countermeasure-on-escape, which reads only the log.
"""

from __future__ import annotations

from collections.abc import Iterable

from zigdag.core.record.entries import Entry
from zigdag.core.record.model import Gate, Record, Workflow
from zigdag.core.rubric import RUBRIC_VERSION
from zigdag.core.findings import Report, Finding, Result, finding
from zigdag.core.log import Answer, Answered, Kind, Log
from zigdag.core.names import is_within
from zigdag.core.log import Actor


def _gates(record: Record) -> list[tuple[str, Gate, str]]:
    """(name, gate, the FR it covers) for every workflow process variable."""
    return [(name, v.kind.gate, v.on.value) for name, v in sorted(record.process.items())
            if isinstance(v.kind, Workflow)]


def _covers(on: str, entry: Entry, root: str | None) -> bool:
    return is_within(entry.scope, on) if entry.scope is not None else on == root


def check_gates(record: Record, log: Log, people: tuple[Actor, ...], changed: list[Entry] | None,
                report: Report) -> Iterable[Finding]:
    root = record.root.name if record.root else None
    for name, gate, on in _gates(record):
        if gate is Gate.COUNTERMEASURE_ON_ESCAPE:
            yield from _countermeasures(name, log)
            continue
        if changed is None:
            continue
        if gate is Gate.STOP_ON_ERROR:
            if report.breaks:
                yield finding(Result.BREAKS, name, "change", None, "the change cannot be accepted while a check breaks")
            continue
        for entry in changed:
            if not _covers(on, entry, root):
                continue
            critiques = log.critiques(entry.name, entry.digest)
            approvals = log.approvals(entry.name, entry.digest)
            if gate is Gate.CRITIQUE_BEFORE_REVIEW:
                current = [c for c in critiques if (c.rubric or 0) >= RUBRIC_VERSION]
                if not current:
                    yield finding(Result.BREAKS, name, entry.name, entry.span,
                                  "needs a critique of its current content (zigdag critique)", entry.digest)
                elif approvals and min(a.at for a in approvals) < min(c.at for c in current):
                    yield finding(Result.BREAKS, name, entry.name, entry.span,
                                  "was approved before it was critiqued", entry.digest)
            elif gate is Gate.PERSON_APPROVES_DESIGN:
                if not any(a.by in people for a in approvals):
                    who = ", ".join(people) if people else "nobody: list people in zigdag.toml [settings] people"
                    yield finding(Result.BREAKS, name, entry.name, entry.span,
                                  f"needs approval of its current content by a person ({who})", entry.digest)


def _countermeasures(name: str, log: Log) -> Iterable[Finding]:
    for thread in log.threads:
        if thread.raised.kind is not Kind.DEFECT:
            continue
        for a in thread.answers:
            if isinstance(a, Answered) and a.answer is Answer.FIXED and not a.countermeasure:
                yield finding(Result.BREAKS, name, thread.raised.on, None,
                              f"defect {thread.raised.id} was fixed without a countermeasure: name the rule, statement "
                              f"or FR that will catch it next time", thread.raised.id)
