"""The tools an adapter has the shell run on a project's code, a linter, a type checker or a security checker, and
what the shell saw of each.

zigdag runs them itself on every check rather than reading reports someone saved: a saved report can be older than
the code, and a lint result about code that is gone is worse than none. They run only when a rule asks for what they
report.
"""

from __future__ import annotations

import enum
import shlex
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import NewType

import deal

from zigdag.core.code import TOOL_FAILED, Diagnosis, Diagnostic, ToolName
from zigdag.core.codec import Unreadable
from zigdag.core.findings import Finding, RecordPath, Result, Subject, finding
from zigdag.core.names import AdapterName, Argument, Key
from zigdag.core.settings import CURRENT_FOLDER, PROJECT_ROOT, Settings
from zigdag.core.texts import Content, Say, ToolText

ExitStatus = NewType("ExitStatus", int)  # what a tool exited with
_SUCCESS = ExitStatus(0)
_SHOWN_LINES = 3  # of a failing tool's error output, so a finding shows why without the whole trace

# How an adapter reads what one of its tools printed: the tool's report, what it diagnoses, and its name.
ReportReader = Callable[[ToolText, Diagnosis, ToolName], "tuple[Diagnostic, ...] | Unreadable"]


@dataclass(frozen=True)
class Tool:
    """A tool an adapter runs. Its name is also its key in the adapter's section of zigdag.toml, which says how to
    start it."""

    adapter: AdapterName
    name: ToolName
    diagnosis: Diagnosis  # what it reports on: one tool for each, so a rule of each kind names its tool
    arguments: tuple[Argument, ...]  # what it is run with, before the folders it reads: what writes the report


class Started(enum.Enum):
    """Whether the shell could start a tool at all."""

    STARTED = "started"
    NOT_FOUND = "not found"


@dataclass(frozen=True)
class ToolRun:
    """How to run one tool on the project, from the project's root."""

    tool: Tool
    command: tuple[Argument, ...]


@dataclass(frozen=True)
class ToolOutput:
    """What the shell saw when it ran a tool."""

    tool: Tool
    started: Started
    status: ExitStatus = _SUCCESS
    out: ToolText = ToolText("")
    err: ToolText = ToolText("")


@deal.ensure(lambda tools, settings, roots, wanted, result: {r.tool.diagnosis for r in result} == (
    set(wanted) & {t.diagnosis for t in tools}))
def runs(tools: Iterable[Tool], settings: Settings, roots: Iterable[RecordPath],
         wanted: Iterable[Diagnosis]) -> tuple[ToolRun, ...]:
    """Those of an adapter's tools that report what the rules want, each started as its adapter's section says, or by
    its own name, on the adapter's folders."""
    folders = tuple(Argument(CURRENT_FOLDER if r == PROJECT_ROOT else r) for r in roots) or (Argument(CURRENT_FOLDER),)
    chosen = set(wanted)
    out = []
    for tool in tools:
        if tool.diagnosis not in chosen:
            continue
        start = shlex.split(settings.command(tool.adapter, Key(tool.name)) or tool.name)
        out.append(ToolRun(tool, (*(Argument(a) for a in start), *tool.arguments, *folders)))
    return tuple(out)


@deal.pure
@deal.ensure(lambda tool, status, out, err, result: result.tool is tool and result.started is Started.STARTED)
@deal.ensure(lambda tool, status, out, err, result: (result.status, result.out, result.err) == (status, out, err))
def finished(tool: Tool, status: ExitStatus, out: ToolText, err: ToolText) -> ToolOutput:
    """What a tool that started printed and exited with."""
    return ToolOutput(tool, Started.STARTED, status, out, err)


@deal.pure
@deal.ensure(lambda tool, result: result.tool is tool and result.started is Started.NOT_FOUND)
def not_started(tool: Tool) -> ToolOutput:
    """A tool the shell could not find."""
    return ToolOutput(tool, Started.NOT_FOUND)


def _failed(output: ToolOutput, say: str) -> Finding:
    # A rule the record puts in force could not be checked, which must not pass as if it held (principle 6).
    return finding(Result.BREAKS, TOOL_FAILED, Subject(output.tool.diagnosis.value), None,
                   Say(f"{output.tool.name} {say}"), Content(say))


@deal.ensure(lambda output, read, result: (result[1] is None) or result[0] == ())  # a failure reports nothing else
def diagnostics(output: ToolOutput, read: ReportReader) -> tuple[tuple[Diagnostic, ...], Finding | None]:
    """What a tool reported, read as its adapter reads its report, or why it reported nothing that can be used."""
    tool = output.tool
    if output.started is Started.NOT_FOUND:
        return (), _failed(output, f"could not be started: install it, or say in [adapters.{tool.adapter}] "
                                   f"{tool.name} = \"...\" how to start it")
    if output.status != _SUCCESS:
        shown = " / ".join(output.err.strip().splitlines()[:_SHOWN_LINES]) or "no error output"
        return (), _failed(output, f"failed (exit {output.status}): {shown}")
    reported = read(output.out, tool.diagnosis, tool.name)
    if isinstance(reported, Unreadable):
        return (), _failed(output, f"wrote a report zigdag cannot read ({reported.say})")
    return reported, None
