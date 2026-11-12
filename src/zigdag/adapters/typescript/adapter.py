"""The TypeScript adapter as the command line asks it (zigdag.adapters.adapter): which of a project's files are
TypeScript's, and how its tools, its tests and its profiler are run. Its tests run with zigdag's watcher for vitest
when the project's vitest config attaches it."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import deal

import posixpath
import shlex
from pathlib import Path

from zigdag.adapters.adapter import EnvironmentName, EnvironmentValue, Files, Profiling, TestRun
from zigdag.adapters.tools import ToolOutput, ToolRun
from zigdag.adapters.typescript import SUFFIXES, TypeScriptFiles, profiler, read_typescript, tools
from zigdag.adapters.typescript.observed import ROOT_VARIABLE, SEEN_FILE, SEEN_VARIABLE, WATCHER_VARIABLE
from zigdag.core.code import CodeModel, Diagnosis, ToolName
from zigdag.core.codec import Unreadable
from zigdag.core.findings import RecordPath
from zigdag.core.profile import Profile
from zigdag.core.names import TYPESCRIPT, AdapterName, Argument, CodePath, Key, ProjectRoot
from zigdag.core.settings import PROJECT_ROOT, WORK_DIR, Settings
from zigdag.core.texts import FileText, Say

PACKAGE = "package.json"  # what a package declares, its dependencies among it
CONFIG = "tsconfig.json"  # how the compiler is set up, its import aliases among it
DECLARATION = ".d.ts"  # a file that only describes code written elsewhere
# How a test file is named, by the conventions of vitest and jest: cart.test.ts, cart.spec.tsx, __tests__/cart.ts.
TEST_MARKS = (".test.", ".spec.")
TEST_FOLDER = "__tests__"
# Not .xml: Python's test reports are every .xml file in zigdag's folder, and this one is not Python's.
REPORT = RecordPath(f"{WORK_DIR}/typescript.junit")
TEST_COMMAND_KEY = Key("test_command")  # in [adapters.typescript]: how the tests are started
CONTRACTS_KEY = Key("contracts")  # in [adapters.typescript]: the project's own module of requires and ensures
DEFAULT_TEST_COMMAND = "npx vitest run"
# What vitest is also told: to print as it does, and to write the report zigdag reads. It takes the report's place
# from its own folder, wherever that is, so the place is given in full.
_REPORTERS = ("--reporter=default", "--reporter=junit")
_REPORT_OPTION = "--outputFile.junit="
# zigdag's watcher for vitest: a file of JavaScript that vitest loads, kept with zigdag's other watchers. It is
# named by where it is, since it is no Python to import.
WATCHER = Path(__file__).parents[2] / "watchers" / "typescript" / "setup.mjs"
_UNWRITTEN = Say("do the tests run with vitest, in a process that Node can profile?")


def _under(path: str, root: str) -> bool:
    return root == PROJECT_ROOT or path.startswith(root + "/")


@dataclass(frozen=True)
class TypeScriptAdapter:
    """TypeScript, as one project has it."""

    settings: Settings
    source_roots: tuple[RecordPath, ...]  # such as "web"

    @staticmethod
    @deal.ensure(lambda settings, result: (result is None) == (TYPESCRIPT not in settings.adapters))
    def of(settings: Settings) -> TypeScriptAdapter | None:
        """TypeScript for a project, as [adapters.typescript] says; None for a project without that section. Its
        source is where `source` says, or anywhere in the project."""
        if TYPESCRIPT not in settings.adapters:
            return None
        configured = settings.source_roots(TYPESCRIPT)
        return TypeScriptAdapter(settings, configured if configured else (RecordPath(PROJECT_ROOT),))

    @property
    @deal.post(lambda result: result == TYPESCRIPT)
    def name(self) -> AdapterName:
        return TYPESCRIPT

    @property
    @deal.ensure(lambda self, result: result == self.source_roots)
    def folders(self) -> tuple[RecordPath, ...]:
        return self.source_roots

    @property
    @deal.post(lambda result: RecordPath(PACKAGE) in result)
    def files(self) -> tuple[RecordPath, ...]:
        return (RecordPath(PACKAGE), RecordPath(CONFIG), REPORT, SEEN_FILE)

    def _inside(self, path: RecordPath) -> bool:
        return any(_under(path, root) for root in self.source_roots)

    @deal.ensure(lambda self, path, result: not result or path.endswith(SUFFIXES))
    def is_test(self, path: RecordPath) -> bool:
        """Whether a file is a test by how it is named, or by being where the project's tests are."""
        named = any(mark in path.rpartition("/")[2] for mark in TEST_MARKS) or TEST_FOLDER in path.split("/")
        return path.endswith(SUFFIXES) and (named or any(_under(path, r) for r in self.settings.test_roots))

    @deal.ensure(lambda self, path, result: not result or (path.endswith(SUFFIXES) and not self.is_test(path)))
    def is_source(self, path: RecordPath) -> bool:
        return (path.endswith(SUFFIXES) and not path.endswith(DECLARATION) and self._inside(path)
                and not self.is_test(path))

    def _named(self, path: RecordPath, name: str) -> bool:
        """Whether a file is one of that name that governs the source: at the project's root, or among the source."""
        return path == name or (path.endswith(f"/{name}") and self._inside(path))

    def _is_own_test(self, path: RecordPath) -> bool:
        """Whether a test file is one of this project's TypeScript: among its source, or where its tests are."""
        return self.is_test(path) and (self._inside(path) or any(_under(path, r) for r in self.settings.test_roots))

    @deal.ensure(lambda self, path, result: result or not self.is_source(path))
    def wants(self, path: RecordPath) -> bool:
        return (path in (REPORT, SEEN_FILE) or self.is_source(path) or self._is_own_test(path) or self._named(path, PACKAGE)
                or self._named(path, CONFIG))

    def _config(self, files: Files) -> RecordPath | None:
        """The folder of the project's tsconfig.json, for tsc to check by: the outermost there is. None when it is
        where tsc runs, which it finds by itself, or when there is none."""
        configs = sorted((p for p in files if self._named(p, CONFIG)), key=lambda p: (p.count("/"), p))
        folder = posixpath.dirname(configs[0]) if configs else ""
        return RecordPath(folder) if folder else None

    @deal.ensure(lambda self, files, wanted, result: all(r.tool.adapter == TYPESCRIPT for r in result))
    @deal.ensure(lambda self, files, wanted, result: not result or any(self.is_source(p) for p in files))
    def tool_runs(self, files: Files, wanted: Iterable[Diagnosis]) -> tuple[ToolRun, ...]:
        if not any(self.is_source(path) for path in files):
            return ()
        return tools.runs(self.settings, self.source_roots, self._config(files), wanted)

    @deal.ensure(lambda self, files, ran=(), *, result: (result is None) == (
        not any(self.is_source(p) for p in files)))
    def read(self, files: Files, ran: Sequence[ToolOutput] = ()) -> CodeModel | None:
        sources = {p: t for p, t in files.items() if self.is_source(p)}
        if not sources:
            return None
        return read_typescript(TypeScriptFiles(sources, self.source_roots,
                                               {p: t for p, t in files.items() if self._named(p, PACKAGE)},
                                               {p: t for p, t in files.items() if self._named(p, CONFIG)},
                                               {p: t for p, t in files.items() if self._is_own_test(p)},
                                               files.get(REPORT), REPORT, tuple(ran), files.get(SEEN_FILE),
                                               self._contracts))

    @property
    def _contracts(self) -> CodePath | None:
        """The module the project names for its own requires and ensures, as a module is named: web/src/contracts."""
        named = self.settings.adapters.get(TYPESCRIPT, {}).get(CONTRACTS_KEY)
        return CodePath(named) if isinstance(named, str) and named else None

    @deal.ensure(lambda self, files, extra, root, result: result is None or not result.watched)  # no watcher yet
    @deal.ensure(lambda self, files, extra, root, result: (result is None) == (
        not any(self._is_own_test(p) for p in files)))
    def test_run(self, files: Files, extra: Sequence[Argument], root: ProjectRoot) -> TestRun | None:
        """The project's test command, with vitest writing the report the next check reads; None when the project
        has no TypeScript tests. The user's extra arguments are for the watched run, which this is not."""
        if not any(self._is_own_test(path) for path in files):
            return None
        start = shlex.split(self.settings.command(TYPESCRIPT, TEST_COMMAND_KEY) or DEFAULT_TEST_COMMAND)
        # The watcher is told where it is, where to write, and where the project is. It runs only where the
        # project's vitest config attaches it; the run is zigdag's either way.
        told = {EnvironmentName(name): EnvironmentValue(str(place)) for name, place in (
            (WATCHER_VARIABLE, WATCHER), (SEEN_VARIABLE, root / SEEN_FILE), (ROOT_VARIABLE, root))}
        return TestRun((*(Argument(a) for a in start), *(Argument(r) for r in _REPORTERS),
                        Argument(f"{_REPORT_OPTION}{root / REPORT}")), environment=told, clears=(SEEN_FILE,))

    @deal.ensure(lambda self, extra, root, result: result.command[-len(extra):] == tuple(extra) if extra else True)
    def profiled_tests(self, extra: Sequence[Argument], root: ProjectRoot) -> Profiling:
        return Profiling(profiler.profiled(self.settings, extra, root), ToolName(profiler.PROFILER), _UNWRITTEN,
                         profiler.full_profile())

    @deal.ensure(lambda self, text, root, result: isinstance(result, Unreadable) or all(
        line.time >= 0 for line in result.lines))
    def read_profile(self, text: FileText, root: ProjectRoot) -> Profile | Unreadable:
        return profiler.read_profile(text, root)
