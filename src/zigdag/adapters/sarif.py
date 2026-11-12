"""SARIF reports: the JSON form that linters and security checkers in many languages write when they do not write a
GitLab Code Quality report (zigdag.adapters.code_quality). tflint and trivy write it, among others.

https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html
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

# The format's levels. Only an error is what a tool's configuration fails on; "none" is said of what does not apply.
_LEVELS = {"error": Severity.ERROR, "warning": Severity.WARNING, "note": Severity.WARNING, "none": Severity.WARNING}
_DEFAULT_LEVEL = "warning"  # what the format says a result without a level has
_FIRST = 1  # where a tool that names no line or column is taken to mean
_FILE_SCHEME, _RELATIVE = "file://", "./"  # prefixes a tool may give a path, which says the same without them


def _where(result: Mapping) -> Span | None:
    """Where a result is: its first location, which the format says is the one it is about."""
    locations = result.get("locations")
    first = locations[0] if isinstance(locations, list) and locations and isinstance(locations[0], Mapping) else {}
    physical = first.get("physicalLocation")
    if not isinstance(physical, Mapping):
        return None
    artifact, region = physical.get("artifactLocation"), physical.get("region")
    uri = artifact.get("uri") if isinstance(artifact, Mapping) else None
    if not isinstance(uri, str) or not uri:
        return None
    region = region if isinstance(region, Mapping) else {}
    line, column = region.get("startLine"), region.get("startColumn")
    return Span(RecordPath(uri.removeprefix(_FILE_SCHEME).removeprefix(_RELATIVE)),
                Line(line if isinstance(line, int) else _FIRST), Column(column if isinstance(column, int) else _FIRST))


def _result(raw: object, diagnosis: Diagnosis, tool: ToolName) -> Diagnostic | None:
    if not isinstance(raw, Mapping):
        return None
    code, message = raw.get("ruleId"), raw.get("message")
    text = message.get("text") if isinstance(message, Mapping) else None
    severity = _LEVELS.get(raw.get("level", _DEFAULT_LEVEL))
    where = _where(raw)
    if not isinstance(code, str) or not isinstance(text, str) or severity is None or where is None:
        return None
    # A message may run over several lines, and a diagnostic is said on one.
    return Diagnostic(diagnosis, tool, DiagnosticCode(code), Say(" ".join(text.split())), where, severity)


@deal.ensure(lambda text, diagnosis, tool, result: isinstance(result, Unreadable) or all(
    d.diagnosis is diagnosis and d.tool == tool for d in result))
def read_sarif(text: ToolText, diagnosis: Diagnosis, tool: ToolName) -> tuple[Diagnostic, ...] | Unreadable:
    """Every result of every run in a report, in the report's order; a report with any result that does not fit is
    refused whole, so that a diagnostic is never silently dropped."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return Unreadable(Say(f"not JSON: {e}"))
    runs = raw.get("runs") if isinstance(raw, Mapping) else None
    if not isinstance(runs, list):
        return Unreadable(Say("not a SARIF report: it has no runs"))
    results = [r for run in runs if isinstance(run, Mapping) for r in (run.get("results") or ())]
    read = [_result(r, diagnosis, tool) for r in results]
    if None in read:
        return Unreadable(Say(f"result {read.index(None) + 1} lacks a rule, a message or a file"))
    return tuple(d for d in read if d is not None)
