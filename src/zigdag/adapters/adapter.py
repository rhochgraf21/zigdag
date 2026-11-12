"""What an adapter is (DESIGN2 §5): the questions the command line asks of each language or tool it can read.

An adapter never touches the project. It says what it needs, the shell fetches it, and the adapter reads the text
that comes back into the code model. So every question here is one half of such an exchange: which files, and what
they hold; which tools, and what they reported; how to run the tests, and what the run wrote.

One protocol serves a language and an infrastructure tool alike. They differ in which parts of the code model they
supply, which the model itself records (CodeModel.supplied), and an adapter that has no tests or no profiler says
so by answering None.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import NewType, Protocol

import deal

from zigdag.adapters.tools import ToolOutput, ToolRun
from zigdag.core.code import CodeModel, Diagnosis, ToolName
from zigdag.core.codec import Unreadable
from zigdag.core.findings import RecordPath
from zigdag.core.names import AdapterName, Argument, ProjectRoot
from zigdag.core.profile import Profile
from zigdag.core.texts import FileText, Say

Files = Mapping[RecordPath, FileText]  # project-relative path -> text, as the shell read it
EnvironmentName = NewType("EnvironmentName", str)  # the name of an environment variable
EnvironmentValue = NewType("EnvironmentValue", str)  # what an environment variable is set to


class Presence(enum.Enum):
    """Whether something is there, as the shell found it: a file, a folder."""

    PRESENT = True
    ABSENT = False


@dataclass(frozen=True)
class TestRun:
    """How an adapter's tests are run. With a watcher, the run is watched: the watcher is told what to watch, and
    writes what the code did. Without one, the tests run as they are, and their report is read at the next check."""

    command: tuple[Argument, ...]  # run from the project's root
    unseen: Say | None = None  # for a watched run: what to look at when it ran and the watcher wrote nothing
    environment: Mapping[EnvironmentName, EnvironmentValue] = field(default_factory=dict)  # what the run is also told, by name
    clears: tuple[RecordPath, ...] = ()  # what the run before wrote that this one writes anew: removed first

    @property
    @deal.ensure(lambda self, result: result == (self.unseen is not None))
    def watched(self) -> bool:
        return self.unseen is not None


@dataclass(frozen=True)
class Profiling:
    """How an adapter's tests are run under its profiler."""

    command: tuple[Argument, ...]  # run from the project's root; it writes the profile to PROFILE_FILE
    profiler: ToolName  # as people know it: scalene
    unwritten: Say  # what to look at when the tests ran and the profiler wrote no profile
    full: Say  # what the profile holds beyond what zigdag shows, and how to open it


class Adapter(Protocol):
    """One language or tool, set up for one project from its section of zigdag.toml.

    A protocol's own methods never run, so the contracts here check nothing by themselves: they say what the command
    line relies on, and each adapter states and keeps the same on its own methods."""

    @property
    @deal.post(lambda result: bool(result))
    def name(self) -> AdapterName:
        """The name its code names are written under: python, terraform."""
        ...

    @property
    @deal.post(lambda result: not any(folder.endswith("/") for folder in result))  # as record paths are written
    def folders(self) -> tuple[RecordPath, ...]:
        """The folders the shell walks for it; the project's root when its files may be anywhere."""
        ...

    @property
    @deal.post(lambda result: not any(file.startswith("/") for file in result))  # inside the project
    def files(self) -> tuple[RecordPath, ...]:
        """The single files it reads wherever they are, since no folder it names need hold them."""
        ...

    @deal.ensure(lambda self, path, result: result or path not in self.files)
    def wants(self, path: RecordPath) -> bool:
        """Whether a file is one it reads."""
        ...

    @deal.ensure(lambda self, files, wanted, result: all(r.tool.adapter == self.name for r in result))
    def tool_runs(self, files: Files, wanted: Iterable[Diagnosis]) -> tuple[ToolRun, ...]:
        """The tools of its own that report what the rules want, and how to run each; none when the project holds
        nothing of its kind for them to read."""
        ...

    @deal.ensure(lambda self, files, ran, result: result is None or all(
        unit.adapter == self.name for unit in result.units.values()))
    def read(self, files: Files, ran: Sequence[ToolOutput]) -> CodeModel | None:
        """Its part of the code model, read from the project's files and from what its tools printed; None when the
        project holds nothing of its kind."""
        ...

    @deal.ensure(lambda self, files, extra, root, result: result is None or bool(result.command))
    def test_run(self, files: Files, extra: Sequence[Argument], root: ProjectRoot) -> TestRun | None:
        """How its tests are run, with its watcher when it has one; None when it has no tests to run here. The extra
        arguments are the user's, for the watched run. The project's root is given for a test runner that must be
        told where to write its report by a full path."""
        ...

    @deal.ensure(lambda self, extra, root, result: result is None or bool(result.command))
    def profiled_tests(self, extra: Sequence[Argument], root: ProjectRoot) -> Profiling | None:
        """How its tests are run under its profiler, which writes the profile to PROFILE_FILE; None when it has no
        profiler. The project's root is given for a profiler that must be told where to write by a full path."""
        ...

    @deal.ensure(lambda self, text, root, result: isinstance(result, Unreadable) or all(
        line.time >= 0 for line in result.lines))
    def read_profile(self, text: FileText, root: ProjectRoot) -> Profile | Unreadable:
        """What a profile its profiler wrote says, line by line."""
        ...
