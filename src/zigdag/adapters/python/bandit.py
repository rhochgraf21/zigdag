"""bandit's JSON report: what Python's security checker found. bandit writes no GitLab Code Quality report, so the
Python adapter reads bandit's own form, into the same diagnostics as every other tool's.

https://bandit.readthedocs.io/en/latest/formatters/json.html
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

# bandit's own severities. A low one is what most projects let stand, such as importing subprocess, so it is a thing
# to do; the rest break. Which tests run at all is bandit's configuration, not zigdag's.
_SEVERITIES = {"LOW": Severity.WARNING, "MEDIUM": Severity.ERROR, "HIGH": Severity.ERROR}
_FIRST_COLUMN = 1  # bandit counts columns from 0; zigdag, as an editor does, from 1
_RELATIVE = "./"  # a prefix bandit gives paths relative to where it ran


def _issue(raw: object, diagnosis: Diagnosis, tool: ToolName) -> Diagnostic | None:
    if not isinstance(raw, Mapping):
        return None
    code, text, path, line = raw.get("test_id"), raw.get("issue_text"), raw.get("filename"), raw.get("line_number")
    severity, offset = _SEVERITIES.get(raw.get("issue_severity")), raw.get("col_offset")
    if not (isinstance(code, str) and isinstance(text, str) and isinstance(path, str) and isinstance(line, int)):
        return None
    if severity is None:
        return None
    column = Column(offset + _FIRST_COLUMN if isinstance(offset, int) else _FIRST_COLUMN)
    return Diagnostic(diagnosis, tool, DiagnosticCode(code), Say(text),
                      Span(RecordPath(path.removeprefix(_RELATIVE)), Line(line), column), severity)


@deal.ensure(lambda text, diagnosis, tool, result: isinstance(result, Unreadable) or all(
    d.diagnosis is diagnosis and d.tool == tool for d in result))
def read_bandit(text: ToolText, diagnosis: Diagnosis, tool: ToolName) -> tuple[Diagnostic, ...] | Unreadable:
    """Every issue bandit found, in its order. A file bandit could not scan, or an issue that does not fit, refuses the
    report whole: a security check that missed a file must not pass as if it had read it."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return Unreadable(Say(f"not JSON: {e}"))
    if not isinstance(raw, Mapping) or not isinstance(raw.get("results"), list):
        return Unreadable(Say("not a bandit report: it has no list of results"))
    errors = raw.get("errors") or []
    if errors:
        first = errors[0].get("filename") if isinstance(errors[0], Mapping) else None
        return Unreadable(Say(f"bandit could not scan {len(errors)} files, the first {first}"))
    issues = [_issue(r, diagnosis, tool) for r in raw["results"]]
    if None in issues:
        return Unreadable(Say(f"result {issues.index(None) + 1} lacks a test id, text, file, line or severity"))
    return tuple(i for i in issues if i is not None)
