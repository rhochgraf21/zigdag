"""TypeScript's linter and type checker: eslint and tsc, and how each one's report is read.

Neither writes a report that other tools write too. eslint prints its own JSON, naming each file by its full path
on disk. tsc prints a line for each error, naming each file from where it ran. Neither can be told to exit with
zero when it finds something, so what each exits with then is known here.
"""

from __future__ import annotations

import json
import posixpath
import re
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import replace

import deal

from zigdag.adapters import tools
from zigdag.adapters.tools import ExitStatus, ReportReader, Tool, ToolOutput, ToolRun
from zigdag.core.code import Diagnosis, Diagnostic, DiagnosticCode, Severity, ToolName
from zigdag.core.codec import Unreadable
from zigdag.core.findings import Finding, RecordPath, Span
from zigdag.core.measures import Column, Line
from zigdag.core.names import TYPESCRIPT, Argument, Key
from zigdag.core.settings import CURRENT_FOLDER, PROJECT_ROOT, Settings
from zigdag.core.texts import Say, ToolText

# eslint exits with 1 when a rule it treats as an error is broken, and with 2 when it could not run.
ESLINT = Tool(TYPESCRIPT, ToolName("eslint"), Diagnosis.LINT, (Argument("--format=json"),), (ExitStatus(1),))
# tsc exits with 1 or 2 when the code has type errors: which of them depends on whether it would have written files.
TSC = Tool(TYPESCRIPT, ToolName("tsc"), Diagnosis.TYPES, (Argument("--noEmit"), Argument("--pretty"), Argument("false")),
           (ExitStatus(1), ExitStatus(2)))
TOOLS = (ESLINT, TSC)
_RUNNER = "npx"  # what starts a tool that a project has installed for itself
_PROJECT = "--project"  # how tsc is told which tsconfig.json to check by
_ESLINT_ERROR = 2  # eslint's own number for a rule set to fail the run; 1 is a warning
_FATAL = DiagnosticCode("fatal")  # what eslint reports without a rule: it could not read the file
_FIRST = 1
_TSC_LINE = re.compile(r"^(?P<path>.+?)\((?P<line>\d+),(?P<column>\d+)\): (?P<kind>error|warning) "
                       r"(?P<code>TS\d+): (?P<say>.*)$")
_TSC_UNPLACED = re.compile(r"^error TS\d+: ")  # an error about the run itself, such as a tsconfig it cannot read


def _number(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else _FIRST


@deal.ensure(lambda text, diagnosis, tool, result: isinstance(result, Unreadable) or all(
    d.diagnosis is diagnosis and d.tool == tool for d in result))
def read_eslint(text: ToolText, diagnosis: Diagnosis, tool: ToolName) -> tuple[Diagnostic, ...] | Unreadable:
    """Every message of every file in eslint's JSON, in its order; a report with a message that does not fit is
    refused whole, so that a diagnostic is never silently dropped."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return Unreadable(Say(f"not JSON: {e}"))
    if not isinstance(raw, list):
        return Unreadable(Say("not a list of files"))
    found = []
    for file in raw:
        path = file.get("filePath") if isinstance(file, Mapping) else None
        messages = file.get("messages") if isinstance(file, Mapping) else None
        if not isinstance(path, str) or not isinstance(messages, list):
            return Unreadable(Say("a file lacks its path or its messages"))
        for message in messages:
            say = message.get("message") if isinstance(message, Mapping) else None
            if not isinstance(say, str):
                return Unreadable(Say(f"a message about {path} says nothing"))
            rule = message.get("ruleId")
            found.append(Diagnostic(
                diagnosis, tool, DiagnosticCode(rule) if isinstance(rule, str) else _FATAL, Say(say),
                Span(RecordPath(path), Line(_number(message.get("line"))), Column(_number(message.get("column")))),
                Severity.ERROR if message.get("severity") == _ESLINT_ERROR else Severity.WARNING))
    return tuple(found)


@deal.ensure(lambda text, diagnosis, tool, result: isinstance(result, Unreadable) or all(
    d.diagnosis is diagnosis and d.tool == tool for d in result))
def read_tsc(text: ToolText, diagnosis: Diagnosis, tool: ToolName) -> tuple[Diagnostic, ...] | Unreadable:
    """Every error tsc printed, one a line; a line that follows an error and is no error of its own is the rest of
    what that error says. An error about the run itself is refused: then tsc did not check the code."""
    found: list[Diagnostic] = []
    for line in text.splitlines():
        placed = _TSC_LINE.match(line)
        if placed is not None:
            found.append(Diagnostic(
                diagnosis, tool, DiagnosticCode(placed["code"]), Say(placed["say"]),
                Span(RecordPath(posixpath.normpath(placed["path"])), Line(int(placed["line"])),
                     Column(int(placed["column"]))),
                Severity.ERROR if placed["kind"] == "error" else Severity.WARNING))
        elif _TSC_UNPLACED.match(line) is not None:
            return Unreadable(Say(line))
        elif found and line.strip():
            found[-1] = replace(found[-1], say=Say(f"{found[-1].say} {line.strip()}"))
    return tuple(found)


_READERS: Mapping[Tool, ReportReader] = {ESLINT: read_eslint, TSC: read_tsc}


def _start(settings: Settings, tool: Tool) -> tuple[Argument, ...]:
    """How a tool is started: as [adapters.typescript] says, or through npx, which finds the project's own."""
    written = settings.command(TYPESCRIPT, Key(tool.name)) or f"{_RUNNER} {tool.name}"
    return tuple(Argument(a) for a in shlex.split(written))


@deal.ensure(lambda settings, roots, config, wanted, result: {r.tool.diagnosis for r in result} == (
    set(wanted) & {t.diagnosis for t in TOOLS}))
def runs(settings: Settings, roots: Iterable[RecordPath], config: RecordPath | None,
         wanted: Iterable[Diagnosis]) -> tuple[ToolRun, ...]:
    """Those of TypeScript's tools that report what the rules want. eslint is given the source folders; tsc is
    given the folder of the project's tsconfig.json, when that is not where it runs."""
    folders = tuple(Argument(CURRENT_FOLDER if r == PROJECT_ROOT else r) for r in roots)
    project = (Argument(_PROJECT), Argument(config)) if config else ()
    given = {ESLINT: folders, TSC: project}
    chosen = set(wanted)
    return tuple(ToolRun(tool, (*_start(settings, tool), *tool.arguments, *given[tool])) for tool in TOOLS
                 if tool.diagnosis in chosen)


@deal.ensure(lambda output, sources, result: (result[1] is None) or result[0] == ())
def diagnostics(output: ToolOutput, sources: Iterable[RecordPath]) -> tuple[tuple[Diagnostic, ...], Finding | None]:
    """What one of TypeScript's tools reported, each diagnostic at the source file it is about, or why the tool
    reported nothing that can be used."""
    known = tuple(sources)
    reported, failure = tools.diagnostics(output, _READERS[output.tool])
    return tuple(replace(d, span=replace(d.span, path=tools.source_meant(d.span.path, known, RecordPath(PROJECT_ROOT))))
                 for d in reported), failure
