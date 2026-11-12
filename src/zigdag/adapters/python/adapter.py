"""The Python adapter as the command line asks it (zigdag.adapters.adapter): which of a project's files are Python's,
and how its tools, its watched tests and its profiler are run. What the files hold is read in the package itself."""

from __future__ import annotations

import fnmatch
import shlex
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import deal

from zigdag.adapters import tools
from zigdag.adapters.adapter import Files, Presence, Profiling, TestRun
from zigdag.adapters.python import PythonFiles, read_python
from zigdag.adapters.python import profiler
from zigdag.adapters.python.tools import TOOLS
from zigdag.adapters.tools import ToolOutput, ToolRun
from zigdag.core.checks.custom import CHECKS_DIR
from zigdag.core.code import CodeModel, Diagnosis, ToolName
from zigdag.core.codec import Unreadable
from zigdag.core.findings import RecordPath
from zigdag.core.names import PYTHON, AdapterName, Argument, ProjectRoot
from zigdag.core.profile import Profile
from zigdag.core.settings import DEFAULT_REPORT, DEFAULT_TEST_COMMAND, OBSERVED_FILE, PROJECT_ROOT, Settings
from zigdag.core.texts import FileText, Say

PYPROJECT = RecordPath("pyproject.toml")
CONVENTIONAL_SOURCE = RecordPath("src")  # where Python source is, when zigdag.toml does not say
SUFFIX = ".py"
WATCHER = "zigdag.watchers.python"  # the pytest plugin that watches the tests run
_PLUGIN_OPTION, _REPORT_OPTION = "-p", "--junitxml"
_UNSEEN = Say("the tests' Python must be able to import zigdag")
_UNWRITTEN = Say(f"is {profiler.PROFILER} installed where the tests run?")


def _under(path: str, root: str) -> bool:
    return root == PROJECT_ROOT or path.startswith(root + "/")


@dataclass(frozen=True)
class PythonAdapter:
    """Python, as one project has it."""

    settings: Settings
    source_roots: tuple[RecordPath, ...]  # such as "src"

    @staticmethod
    @deal.post(lambda result: bool(result.source_roots))  # source is always somewhere, if only the project itself
    def of(settings: Settings, conventional_source: Presence) -> PythonAdapter:
        """Python for a project: its source where [adapters.python] says, or in the conventional folder when the
        project has one, or anywhere in the project."""
        configured = settings.source_roots(PYTHON)
        default = (CONVENTIONAL_SOURCE,) if conventional_source is Presence.PRESENT else (RecordPath(PROJECT_ROOT),)
        return PythonAdapter(settings, configured if configured is not None else default)

    @property
    @deal.post(lambda result: result == PYTHON)
    def name(self) -> AdapterName:
        return PYTHON

    @property
    @deal.ensure(lambda self, result: set(self.source_roots) <= set(result))
    def folders(self) -> tuple[RecordPath, ...]:
        return (*self.source_roots, *self.settings.test_roots)

    @property
    @deal.post(lambda result: PYPROJECT in result)
    def files(self) -> tuple[RecordPath, ...]:
        return (PYPROJECT, OBSERVED_FILE)

    @deal.ensure(lambda self, path, result: not result or (path.endswith(SUFFIX) and not self.is_test(path)))
    def is_source(self, path: RecordPath) -> bool:
        # A file of custom checks is the project's design, not its code: where the source is the whole project, it
        # must not be read as a module that some design parameter has to own.
        return path.endswith(SUFFIX) and any(_under(path, r) for r in self.source_roots) and not (
            self.is_test(path) or _under(path, CHECKS_DIR))

    @deal.ensure(lambda self, path, result: not result or path.endswith(SUFFIX))
    def is_test(self, path: RecordPath) -> bool:
        return path.endswith(SUFFIX) and any(_under(path, r) for r in self.settings.test_roots)

    @deal.ensure(lambda self, path, result: result or path not in self.settings.report_patterns)  # a plain name
    def is_report(self, path: RecordPath) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.settings.report_patterns)

    @deal.ensure(lambda self, path, result: result or not (self.is_source(path) or self.is_test(path)))
    def wants(self, path: RecordPath) -> bool:
        return path in self.files or self.is_source(path) or self.is_test(path) or self.is_report(path)

    @deal.ensure(lambda self, files, ran=(), *, result: result is None or bool(result.sources))
    def python_files(self, files: Files, ran: Sequence[ToolOutput] = ()) -> PythonFiles | None:
        """What is read of the project, with what Python's tools printed, or None when there is no Python source."""
        sources = {p: t for p, t in files.items() if self.is_source(p)}
        if not sources:
            return None
        return PythonFiles(sources, self.source_roots, self.settings.vendor,
                           {p: t for p, t in files.items() if self.is_test(p)}, files.get(PYPROJECT),
                           {p: t for p, t in files.items() if self.is_report(p)}, files.get(OBSERVED_FILE),
                           tuple(ran))

    @deal.ensure(lambda self, files, ran=(), *, result: (result is None) == (self.python_files(files) is None))
    def read(self, files: Files, ran: Sequence[ToolOutput] = ()) -> CodeModel | None:
        python = self.python_files(files, ran)
        return read_python(python) if python is not None else None

    @deal.ensure(lambda self, files, wanted, result: all(r.tool.adapter == PYTHON for r in result))
    @deal.ensure(lambda self, files, wanted, result: not result or any(self.is_source(p) for p in files))
    def tool_runs(self, files: Files, wanted: Iterable[Diagnosis]) -> tuple[ToolRun, ...]:
        if not any(self.is_source(path) for path in files):
            return ()
        return tools.runs(TOOLS, self.settings, self.source_roots, wanted)

    @deal.ensure(lambda self, files, extra, root, result: result is None or (
        WATCHER in result.command and result.watched))
    @deal.ensure(lambda self, files, extra, root, result: (result is None) == (
        not any(self.is_source(p) for p in files)))
    def test_run(self, files: Files, extra: Sequence[Argument], root: ProjectRoot) -> TestRun | None:
        """The project's test command, with zigdag's pytest plugin watching, and a report written where the next
        check reads it; None when there is no Python source to watch."""
        if not any(self.is_source(path) for path in files):
            return None
        start = shlex.split(self.settings.test_command or DEFAULT_TEST_COMMAND)
        return TestRun((*(Argument(a) for a in start), Argument(_PLUGIN_OPTION), Argument(WATCHER),
                         Argument(f"{_REPORT_OPTION}={DEFAULT_REPORT}"), *extra), _UNSEEN)

    @deal.ensure(lambda self, extra, root, result: result.command[-len(extra):] == tuple(extra) if extra else True)
    def profiled_tests(self, extra: Sequence[Argument], root: ProjectRoot) -> Profiling:
        return Profiling(profiler.profiled(self.settings, extra), ToolName(profiler.PROFILER), _UNWRITTEN,
                         profiler.full_profile(self.settings))

    @deal.ensure(lambda self, text, root, result: isinstance(result, Unreadable) or all(
        line.time >= 0 for line in result.lines))
    def read_profile(self, text: FileText, root: ProjectRoot) -> Profile | Unreadable:
        return profiler.read_profile(text, root)
