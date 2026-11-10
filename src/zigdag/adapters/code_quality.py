"""GitLab Code Quality reports: the one JSON form that linters and type checkers in many languages can write, so each
adapter reads its tools' diagnostics the same way.

https://docs.gitlab.com/ci/testing/code_quality/#code-quality-report-format
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import deal

from zigdag.core.code import Diagnosis, Diagnostic, DiagnosticCode, Severity, ToolName
from zigdag.core.codec import Unreadable
from zigdag.core.findings import RecordPath, Span
from zigdag.core.measures import Column, Line
from zigdag.core.texts import Say, ToolText

# The format's five severities. Its two lowest are what tools write for what their configuration does not fail on.
_SEVERITIES = {"info": Severity.WARNING, "minor": Severity.WARNING, "major": Severity.ERROR,
               "critical": Severity.ERROR, "blocker": Severity.ERROR}
_DEFAULT_SEVERITY = "major"  # the format makes severity optional; an issue that does not say is taken to count
_FIRST = 1  # where a tool that names no line or column is taken to mean
_RELATIVE = "./"  # a prefix some tools give paths relative to where they ran


def _place(location: Mapping) -> tuple[Line, Column] | None:
    """Where an issue begins: the format gives either a line range or exact positions."""
    lines, positions = location.get("lines"), location.get("positions")
    if isinstance(lines, Mapping) and isinstance(lines.get("begin"), int):
        return Line(lines["begin"]), Column(_FIRST)
    begin = positions.get("begin") if isinstance(positions, Mapping) else None
    if isinstance(begin, Mapping) and isinstance(begin.get("line"), int):
        column = begin.get("column")
        return Line(begin["line"]), Column(column if isinstance(column, int) else _FIRST)
    return None


def _issue(raw: object, diagnosis: Diagnosis, tool: ToolName) -> Diagnostic | None:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("location"), Mapping):
        return None
    code, description, path = raw.get("check_name"), raw.get("description"), raw["location"].get("path")
    severity = _SEVERITIES.get(raw.get("severity", _DEFAULT_SEVERITY))
    place = _place(raw["location"])
    if not isinstance(code, str) or not isinstance(description, str) or not isinstance(path, str):
        return None
    if severity is None or place is None:
        return None
    say = description.removeprefix(f"{code}: ")  # both ruff and ty repeat the code at the start of the description
    line, column = place
    return Diagnostic(diagnosis, tool, DiagnosticCode(code), Say(say), Span(RecordPath(path.removeprefix(_RELATIVE)),
                                                                           line, column), severity)


@deal.ensure(lambda text, diagnosis, tool, result: isinstance(result, Unreadable) or all(
    d.diagnosis is diagnosis and d.tool == tool for d in result))
def read_report(text: ToolText, diagnosis: Diagnosis, tool: ToolName) -> tuple[Diagnostic, ...] | Unreadable:
    """Every issue in a report, in the report's order; a report with any issue that does not fit is refused whole, so
    that a diagnostic is never silently dropped."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return Unreadable(Say(f"not JSON: {e}"))
    if not isinstance(raw, list):
        return Unreadable(Say("not a list of issues"))
    issues = [_issue(r, diagnosis, tool) for r in raw]
    if None in issues:
        return Unreadable(Say(f"issue {issues.index(None) + 1} lacks a check name, description, path or line"))
    return tuple(i for i in issues if i is not None)
