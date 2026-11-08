"""Reading what zigdag needs of a project, from disk or from a git revision. Everything after this works on text.

Settings are read first, because they say where the source and tests are; then only those folders are read.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from zigdag.adapters.python import PythonFiles, read_python
from zigdag.core.checks.run import ProjectFiles
from zigdag.core.code import CodeModel
from zigdag.core.findings import RecordPath
from zigdag.core.log import LOG_FILE
from zigdag.core.names import PYTHON
from zigdag.core.record.read import DESIGN_DIR, DESIGN_SUFFIX
from zigdag.core.settings import OBSERVED_FILE, PROJECT_ROOT, SETTINGS_FILE, WORK_DIR, Settings, read_settings

PYPROJECT = RecordPath("pyproject.toml")
CONVENTIONAL_SOURCE = "src"  # where Python source is, when zigdag.toml does not say
PYTHON_SUFFIX = ".py"
SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__"})
HIDDEN_PREFIX = "."
DESIGN_DEPTHS = (2, 3)  # design/<domain>.yaml, and design/<domain>/<part>.yaml
ALWAYS_READ = frozenset({RecordPath(SETTINGS_FILE), PYPROJECT, LOG_FILE, OBSERVED_FILE})

Files = Mapping[RecordPath, str]  # project-relative path -> text


def _visited(folder: str) -> bool:
    """Whether a folder is worth looking in: not hidden (except zigdag's own), not a cache."""
    return folder not in SKIPPED_FOLDERS and (not folder.startswith(HIDDEN_PREFIX) or folder == WORK_DIR)


def _under(path: str, root: str) -> bool:
    return root == PROJECT_ROOT or path.startswith(root + "/")


@dataclass(frozen=True)
class _Plan:
    """What to read, once the settings are known."""

    settings: Settings
    source_roots: tuple[str, ...]

    @staticmethod
    def of(settings_text: str | None, has_conventional_source: bool) -> _Plan:
        settings, _ = read_settings(settings_text)
        configured = settings.source_roots(PYTHON)
        default = (CONVENTIONAL_SOURCE,) if has_conventional_source else (PROJECT_ROOT,)
        return _Plan(settings, configured if configured is not None else default)

    @property
    def folders(self) -> tuple[str, ...]:
        """The folders to walk; the whole project when the source is the project itself."""
        if PROJECT_ROOT in self.source_roots:
            return (PROJECT_ROOT,)
        return (DESIGN_DIR, WORK_DIR, *self.source_roots, *self.settings.test_roots)

    def is_source(self, path: str) -> bool:
        return path.endswith(PYTHON_SUFFIX) and any(_under(path, r) for r in self.source_roots) and not self.is_test(
            path)

    def is_test(self, path: str) -> bool:
        return path.endswith(PYTHON_SUFFIX) and any(_under(path, r) for r in self.settings.test_roots)

    def is_report(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.settings.report_patterns)

    def wants(self, path: str) -> bool:
        parts = path.split("/")
        if not all(_visited(p) for p in parts[:-1]):
            return False
        is_design = parts[0] == DESIGN_DIR and path.endswith(DESIGN_SUFFIX) and len(parts) in DESIGN_DEPTHS
        return path in ALWAYS_READ or is_design or self.is_source(path) or self.is_test(path) or self.is_report(path)


def _chosen(plan: _Plan, paths: Iterable[str], read: Callable[[str], str]) -> dict[RecordPath, str]:
    return {RecordPath(p): read(p) for p in sorted(set(paths)) if plan.wants(p)}


def from_disk(root: Path) -> dict[RecordPath, str]:
    settings_path = root / SETTINGS_FILE
    plan = _Plan.of(settings_path.read_text(encoding="utf-8") if settings_path.is_file() else None,
                    (root / CONVENTIONAL_SOURCE).is_dir())
    paths = [name for name in ALWAYS_READ if (root / name).is_file()]
    for folder in plan.folders:
        base = root / folder
        if not base.is_dir():
            continue
        for here, folders, names in os.walk(base):
            folders[:] = sorted(f for f in folders if _visited(f))
            paths += [(Path(here) / name).relative_to(root).as_posix() for name in names]
    return _chosen(plan, paths, lambda path: (root / path).read_text(encoding="utf-8"))


class GitError(Exception):
    """A git revision could not be read."""


_MISSING = "missing"  # what `git cat-file --batch` says instead of a size for a path absent at the revision


def _object_size(header: str) -> int | None:
    """The size from a `git cat-file --batch` header: `<object> <type> <size>`, or `<name> missing`."""
    last = header.rsplit(" ", 1)[-1]
    return None if last == _MISSING else int(last)


def _git(root: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, input=stdin)


def _git_read(root: Path, revision: str, paths: list[str]) -> dict[str, str]:
    """The text of each path at the revision, read in one git process. Paths absent there are left out."""
    out = _git(root, "cat-file", "--batch", stdin="".join(f"{revision}:{p}\n" for p in paths).encode()).stdout
    texts: dict[str, str] = {}
    at = 0
    for path in paths:
        end = out.index(b"\n", at)
        size = _object_size(out[at:end].decode())
        at = end + 1
        if size is not None:
            texts[path] = out[at:at + size].decode("utf-8", errors="replace")
            at += size + 1  # the content is followed by a newline
    return texts


def from_git(root: Path, revision: str) -> dict[RecordPath, str]:
    """The project's files as they are at a git revision."""
    listed = _git(root, "ls-tree", "-r", "--name-only", revision)
    if listed.returncode != 0:
        raise GitError(listed.stderr.decode().strip() or f"cannot read {revision}")
    paths = listed.stdout.decode().splitlines()
    settings_text = _git_read(root, revision, [SETTINGS_FILE]).get(SETTINGS_FILE) if SETTINGS_FILE in paths else None
    plan = _Plan.of(settings_text, any(_under(p, CONVENTIONAL_SOURCE) for p in paths))
    texts = _git_read(root, revision, [p for p in paths if plan.wants(p)])
    return _chosen(plan, texts, texts.__getitem__)


def project_files(files: Files) -> ProjectFiles:
    design = {p: t for p, t in files.items() if p.startswith(DESIGN_DIR + "/") and p.endswith(DESIGN_SUFFIX)}
    return ProjectFiles(files.get(RecordPath(SETTINGS_FILE)), design, files.get(LOG_FILE))


def python_files(files: Files) -> PythonFiles | None:
    """What the Python adapter reads, or None when there is no Python source."""
    plan = _plan_of(files)
    sources = {p: t for p, t in files.items() if plan.is_source(p)}
    if not sources:
        return None
    return PythonFiles(sources, plan.source_roots, plan.settings.vendor,
                       {p: t for p, t in files.items() if plan.is_test(p)}, files.get(PYPROJECT),
                       {p: t for p, t in files.items() if plan.is_report(p)}, files.get(OBSERVED_FILE))


def _plan_of(files: Files) -> _Plan:
    return _Plan.of(files.get(RecordPath(SETTINGS_FILE)), any(_under(p, CONVENTIONAL_SOURCE) for p in files))


def source_roots(files: Files) -> tuple[str, ...]:
    """Where the project's Python source is."""
    return _plan_of(files).source_roots


def test_files(files: Files) -> dict[RecordPath, str]:
    plan = _plan_of(files)
    return {p: t for p, t in files.items() if plan.is_test(p)}


def code_model(files: Files) -> CodeModel | None:
    python = python_files(files)
    return read_python(python) if python is not None else None
