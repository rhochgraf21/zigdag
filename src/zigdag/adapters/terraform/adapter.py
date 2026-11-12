"""The Terraform adapter as the command line asks it (zigdag.adapters.adapter): which of a project's files are
Terraform's, and how its tools and its tests are run. It has no watcher and no profiler."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import deal

import shlex

from zigdag.adapters.adapter import Files, TestRun
from zigdag.adapters.terraform import SUFFIX, TerraformFiles, read_terraform
from zigdag.adapters.terraform import tests, tools
from zigdag.adapters.terraform.tests import Mode
from zigdag.adapters.tools import ToolOutput, ToolRun
from zigdag.core.code import CodeModel, Diagnosis
from zigdag.core.codec import Unreadable
from zigdag.core.findings import RecordPath
from zigdag.core.names import TERRAFORM, AdapterName, Argument, Identifier, Key, ProjectRoot
from zigdag.core.settings import CURRENT_FOLDER, PROJECT_ROOT, SOURCE_KEY, WORK_DIR, Settings
from zigdag.core.texts import FileText, Say

PLAN_KEY = Key("plan")  # in [adapters.terraform]: where the rendered plan is
CONTAINERS_KEY = Key("containers")  # in [adapters.terraform]: resource types that are containers too
TEST_KEY = Key("test")  # in [adapters.terraform]: "plan" (as assumed) or "apply", what its tests may do
COMMAND_KEY = Key("terraform")  # in [adapters.terraform]: how to start Terraform, such as "tofu"
DEFAULT_PLAN = RecordPath(f"{WORK_DIR}/plan.json")
# Not .xml: Python's test reports are every .xml file in zigdag's folder, and this one is not Python's.
REPORT = RecordPath(f"{WORK_DIR}/terraform.junit")
_NO_PROFILER = Say("Terraform has no profiler")


def _folder(written: str) -> RecordPath:
    return RecordPath(PROJECT_ROOT if written == CURRENT_FOLDER else written.rstrip("/"))


def _under(path: str, root: str) -> bool:
    return root == PROJECT_ROOT or path.startswith(root + "/")


@dataclass(frozen=True)
class TerraformAdapter:
    """Terraform, as one project has it."""

    settings: Settings
    root: RecordPath  # the folder of the root module, which the plan is rendered from
    modules: tuple[RecordPath, ...]  # other folders that hold source: modules kept outside the root module's folder
    plan: RecordPath
    containers: frozenset[Identifier]
    mode: Mode

    @staticmethod
    @deal.ensure(lambda settings, result: (result is None) == (TERRAFORM not in settings.adapters))
    def of(settings: Settings) -> TerraformAdapter | None:
        """Terraform for a project, as [adapters.terraform] says; None for a project without that section, since
        nothing says where its infrastructure is described. `source` is the root module's folder, or a list that
        begins with it; without it, the root module is the project's own folder. Tests only plan unless `test` says
        they may apply."""
        section = settings.adapters.get(TERRAFORM)
        if section is None:
            return None
        source, plan, containers = section.get(SOURCE_KEY), section.get(PLAN_KEY), section.get(CONTAINERS_KEY)
        listed = [source] if isinstance(source, str) else source if isinstance(source, list) else []
        folders = tuple(_folder(f) for f in listed if isinstance(f, str)) or (RecordPath(PROJECT_ROOT),)
        mode = Mode.APPLY if section.get(TEST_KEY) == Mode.APPLY.value else Mode.PLAN
        return TerraformAdapter(settings, folders[0], folders[1:],
                                RecordPath(plan) if isinstance(plan, str) else DEFAULT_PLAN,
                                frozenset(Identifier(c) for c in containers if isinstance(c, str))
                                if isinstance(containers, list) else frozenset(), mode)

    @property
    @deal.post(lambda result: result == TERRAFORM)
    def name(self) -> AdapterName:
        return TERRAFORM

    @property
    @deal.ensure(lambda self, result: result[0] == self.root)
    def folders(self) -> tuple[RecordPath, ...]:
        return (self.root, *self.modules)

    @property
    @deal.ensure(lambda self, result: self.plan in result)
    def files(self) -> tuple[RecordPath, ...]:
        return (self.plan, REPORT)

    @deal.ensure(lambda self, path, result: not result or path.endswith(SUFFIX))
    def is_source(self, path: RecordPath) -> bool:
        return path.endswith(SUFFIX) and any(_under(path, folder) for folder in self.folders)

    @deal.ensure(lambda self, path, result: not result or not self.is_source(path))
    def is_test(self, path: RecordPath) -> bool:
        return path.endswith(tests.SUFFIX) and any(_under(path, folder) for folder in self.folders)

    @deal.ensure(lambda self, path, result: result == (path in self.files or self.is_source(path)
                                                       or self.is_test(path)))
    def wants(self, path: RecordPath) -> bool:
        return path in self.files or self.is_source(path) or self.is_test(path)

    def _tests(self, files: Files) -> dict[RecordPath, FileText]:
        return {p: t for p, t in files.items() if self.is_test(p)}

    @deal.ensure(lambda self, files, wanted, result: all(r.tool.adapter == TERRAFORM for r in result))
    @deal.ensure(lambda self, files, wanted, result: not result or any(self.is_source(p) for p in files))
    def tool_runs(self, files: Files, wanted: Iterable[Diagnosis]) -> tuple[ToolRun, ...]:
        if not any(self.is_source(path) for path in files):
            return ()
        return tools.runs(self.settings, self.root, wanted)

    @deal.ensure(lambda self, files, ran=(), *, result: (result is None) == (
        self.plan not in files and not any(self.is_source(p) for p in files)))
    def read(self, files: Files, ran: Sequence[ToolOutput] = ()) -> CodeModel | None:
        sources = {p: t for p, t in files.items() if self.is_source(p)}
        if not sources and self.plan not in files:
            return None
        return read_terraform(TerraformFiles(sources, self.root, files.get(self.plan), self.plan, self.containers,
                                             self._tests(files), files.get(REPORT), REPORT, self.mode, tuple(ran)))

    @deal.ensure(lambda self, files, extra, root, result: result is None or not result.watched)  # it has no watcher
    def test_run(self, files: Files, extra: Sequence[Argument], root: ProjectRoot) -> TestRun | None:
        """How the test files that may run are run, their report written where the next check reads it; None when
        there are none. The user's extra arguments are for the watched run, which this is not."""
        runnable = tests.runnable(self._tests(files), self.mode)
        if not runnable:
            return None
        start = tuple(Argument(a) for a in shlex.split(
            self.settings.command(TERRAFORM, COMMAND_KEY) or COMMAND_KEY))
        return TestRun(tests.command(start, self.root, runnable, REPORT))

    @deal.post(lambda result: result is None)
    def profiled_tests(self, extra: Sequence[Argument], root: ProjectRoot) -> None:
        return None

    @deal.post(lambda result: isinstance(result, Unreadable))
    def read_profile(self, text: FileText, root: ProjectRoot) -> Unreadable:
        return Unreadable(_NO_PROFILER)
