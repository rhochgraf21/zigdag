"""The Python linter, type checker and security checker, ruff, ty and bandit: how the shell runs them, and what their
output says.

zigdag runs them itself on every check rather than reading reports someone saved: a saved report can be older than
the code, and a lint result about code that is gone is worse than none. Both are fast enough that this costs little.
They run only when a rule asks for what they report.
"""

from __future__ import annotations

import enum
import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import NewType

import deal

from zigdag.adapters.code_quality import read_report
from zigdag.adapters.python.bandit import read_bandit
from zigdag.core.code import TOOL_FAILED, Diagnosis, Diagnostic, ToolName
from zigdag.core.codec import Unreadable
from zigdag.core.findings import Finding, RecordPath, Result, Subject, finding
from zigdag.core.names import PYTHON, Argument, Key
from zigdag.core.settings import CURRENT_FOLDER, PROJECT_ROOT, Settings
from zigdag.core.texts import Content, Say, ToolText

ExitStatus = NewType("ExitStatus", int)  # what a tool exited with
_SUCCESS = ExitStatus(0)
_CODE_QUALITY = ("check", "--output-format=gitlab", "--exit-zero")  # ruff and ty alike: one form, and no failing
_BANDIT = ("--format=json", "--exit-zero", "--quiet", "--recursive")  # bandit writes only its own form
_SHOWN_LINES = 3  # of a failing tool's error output, so a finding shows why without the whole trace


class Tool(enum.Enum):
    """A tool the Python adapter runs. Its value is also its key in [adapters.python], which says how to start it."""

    RUFF = "ruff"
    TY = "ty"
    BANDIT = "bandit"

    @property
    @deal.ensure(lambda self, result: result in Diagnosis)
    def diagnosis(self) -> Diagnosis:
        """What it reports on: one tool for each, so a rule of each kind names its tool."""
        return _DIAGNOSIS[self]

    @property
    @deal.ensure(lambda self, result: "--exit-zero" in result)  # finding something is no failure to run
    def arguments(self) -> tuple[Argument, ...]:
        """What it is run with, before the folders it reads: whatever writes the report zigdag reads."""
        return tuple(Argument(a) for a in (_BANDIT if self is Tool.BANDIT else _CODE_QUALITY))

    @property
    def name_shown(self) -> ToolName:
        return ToolName(self.value)


class Started(enum.Enum):
    """Whether the shell could start a tool at all."""

    STARTED = "started"
    NOT_FOUND = "not found"


_DIAGNOSIS: Mapping[Tool, Diagnosis] = {Tool.RUFF: Diagnosis.LINT, Tool.TY: Diagnosis.TYPES,
                                        Tool.BANDIT: Diagnosis.SECURITY}


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


@deal.ensure(lambda settings, roots, wanted, result: {r.tool.diagnosis for r in result} == set(wanted))
def runs(settings: Settings, roots: Iterable[RecordPath], wanted: Iterable[Diagnosis]) -> tuple[ToolRun, ...]:
    """The tools for what the rules want, each started as [adapters.python] says, or by its own name."""
    folders = tuple(Argument(CURRENT_FOLDER if r == PROJECT_ROOT else r) for r in roots) or (Argument(CURRENT_FOLDER),)
    chosen = set(wanted)
    out = []
    for tool in Tool:
        if tool.diagnosis not in chosen:
            continue
        start = shlex.split(settings.command(PYTHON, Key(tool.value)) or tool.value)
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
                   Say(f"{output.tool.value} {say}"), Content(say))


def diagnostics(output: ToolOutput) -> tuple[tuple[Diagnostic, ...], Finding | None]:
    """What a tool reported, or why it reported nothing that can be used."""
    if output.started is Started.NOT_FOUND:
        return (), _failed(output, f"could not be started: install it, or say in [adapters.python] {output.tool.value} "
                                   f"= \"...\" how to start it")
    if output.status != _SUCCESS:
        shown = " / ".join(output.err.strip().splitlines()[:_SHOWN_LINES]) or "no error output"
        return (), _failed(output, f"failed (exit {output.status}): {shown}")
    reader = read_bandit if output.tool is Tool.BANDIT else read_report  # bandit writes no GitLab report
    read = reader(output.out, output.tool.diagnosis, output.tool.name_shown)
    if isinstance(read, Unreadable):
        return (), _failed(output, f"wrote a report zigdag cannot read ({read.say})")
    return read, None

