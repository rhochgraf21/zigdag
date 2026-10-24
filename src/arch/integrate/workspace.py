"""Load and persist what arch reads and writes in a project.

Realizes arch.integrate.workspace: the only component that touches the filesystem (shell-io).
Hides filesystem layout; the core only ever sees snapshots as data.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NewType

from arch import realize
from arch.change import DesignEdit, SourceEdit
from arch.check import Baseline, BaselineText, Lexicon, Term
from arch.model import codec
from arch.model.ids import DesignPath
from arch.model.schema import Design
from arch.realize.facts import FileChange, Facts, LineNo, Roots, Snapshot, SourcePath, SourceText, VcsLog
from arch.realize.history import CommitWindow, NumStat, parse_numstat

Revision = NewType("Revision", str)  # anything git accepts, e.g. HEAD or a commit id

DESIGN_DIR = "design"
CONFIG_FILE = "arch.toml"
_SKIP_DIRS = frozenset({"__pycache__", "node_modules", "venv", "build", "dist", DESIGN_DIR})


class NoProject(Exception):
    pass


class BadConfig(Exception):
    pass


ProjectPath = NewType("ProjectPath", str)  # '/'-separated, relative to the project root


@dataclass(frozen=True)
class ProjectEdit:
    """A change to any project file (agent configuration, AGENTS.md); None before means it is created."""

    path: ProjectPath
    before: SourceText | None
    after: SourceText


class StaleEdit(Exception):
    """A file changed on disk since it was read; nothing was written."""


class NoRevision(Exception):
    pass


class AlreadyDesigned(Exception):
    """`init` would overwrite an existing design."""


@dataclass(frozen=True)
class ProjectConfig:
    """What `arch.toml` says; every field optional. Parsed here, at the edge, into typed values."""

    source_roots: tuple[SourcePath, ...] | None = None
    test_roots: tuple[SourcePath, ...] | None = None
    junit: tuple[SourcePath, ...] = (SourcePath(".arch/evidence/*.xml"),)  # glob patterns for test reports
    history_commits: CommitWindow = CommitWindow(500)
    solution_terms: tuple[Term, ...] = ()  # added to arch.check.statements' lexicons
    vague_terms: tuple[Term, ...] = ()

    @staticmethod
    def read(path: Path) -> ProjectConfig:
        if not path.is_file():
            return ProjectConfig()
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise BadConfig(f"{path.name}: {e}") from e
        roots = raw.get("roots", {})
        evidence = raw.get("evidence", {})
        history = raw.get("history", {})
        commits = history.get("commits", 500) if isinstance(history, dict) else 500
        if not isinstance(commits, int) or isinstance(commits, bool) or commits < 0:
            raise BadConfig(f"{path.name}: history.commits must be a non-negative integer")
        statements = raw.get("statements", {})
        return ProjectConfig(
            _paths(roots, "source", path), _paths(roots, "tests", path),
            _paths(evidence, "junit", path) or ProjectConfig.junit, CommitWindow(commits),
            tuple(Term(t) for t in _paths(statements, "solution_terms", path) or ()),
            tuple(Term(t) for t in _paths(statements, "vague_terms", path) or ()),
        )

    def lexicon(self) -> Lexicon:
        return Lexicon().extended(self.solution_terms, self.vague_terms)


def _paths(table: object, key: str, path: Path) -> tuple[SourcePath, ...] | None:
    value = table.get(key) if isinstance(table, dict) else None
    if value is None:
        return None
    if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
        raise BadConfig(f"{path.name}: roots.{key} must be a list of paths")
    return tuple(SourcePath(v.strip("/")) for v in value)


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def design_dir(self) -> Path:
        return self.root / DESIGN_DIR

    def design_files(self) -> Mapping[DesignPath, codec.SourceText]:
        files = {}
        for path in sorted(self.design_dir.rglob("*.md")):
            rel = DesignPath(path.relative_to(self.design_dir).as_posix())
            if codec.node_id(rel) is not None:
                files[rel] = path.read_text(encoding="utf-8")
        return files

    def design(self) -> Design:
        return codec.load(self.design_files())

    def config(self) -> ProjectConfig:
        return ProjectConfig.read(self.root / CONFIG_FILE)

    def roots(self) -> Roots:
        """From arch.toml `[roots]`, else `src/` (or the project root) and `tests/`."""
        config = self.config()
        source = config.source_roots or ((SourcePath("src"),) if (self.root / "src").is_dir() else (SourcePath(""),))
        tests = config.test_roots if config.test_roots is not None else (
            (SourcePath("tests"),) if (self.root / "tests").is_dir() else ())
        return Roots(source, tests)

    def snapshot(self) -> Snapshot:
        roots = self.roots()
        files: dict[SourcePath, str] = {}
        for base in (*roots.source, *roots.test):
            top = self.root / base
            for path in sorted(top.rglob("*.py")):
                rel = path.relative_to(self.root)
                if any(p.startswith(".") or p in _SKIP_DIRS for p in rel.parts[:-1]):
                    continue
                files.setdefault(SourcePath(rel.as_posix()), path.read_text(encoding="utf-8", errors="replace"))
        config = self.config()
        reports = {SourcePath(p.relative_to(self.root).as_posix()): p.read_text(encoding="utf-8", errors="replace")
                   for pattern in config.junit for p in sorted(self.root.glob(pattern)) if p.is_file()}
        mutation = {SourcePath(p.relative_to(self.root).as_posix()): p.read_text(encoding="utf-8", errors="replace")
                    for p in sorted((self.root / "mutants").rglob("*.meta")) if p.is_file()}
        return Snapshot(files, roots, self._log(config.history_commits), reports, mutation)

    def _log(self, commits: CommitWindow) -> VcsLog | None:
        """Recent history for the source roots, or None outside a git repository."""
        if commits == 0 or not (self.root / ".git").exists() and not self._inside_git():
            return None
        try:
            return VcsLog(self._git("log", f"-n{commits}", "--numstat", "--no-renames", "--format=commit %H", "--", "."))
        except NoRevision:
            return None

    def _inside_git(self) -> bool:
        try:
            self._git("rev-parse", "--is-inside-work-tree")
            return True
        except NoRevision:
            return False

    def facts(self) -> Facts:
        return realize.extract(self.snapshot())

    @property
    def baseline_path(self) -> Path:
        return self.design_dir / "baseline"

    def baseline(self) -> Baseline:
        path = self.baseline_path
        return Baseline.parse(BaselineText(path.read_text(encoding="utf-8"))) if path.is_file() else Baseline()

    def write_baseline(self, baseline: Baseline) -> None:
        tmp = self.baseline_path.with_suffix(".arch-tmp")
        tmp.write_text(baseline.render(), encoding="utf-8")
        os.replace(tmp, self.baseline_path)

    def read_input(self, path: Path) -> SourceText:
        """A file named on the command line (e.g. a batch of operations), relative to the working directory."""
        return path.read_text(encoding="utf-8")

    def design_at(self, revision: Revision) -> Design:
        """The design as committed at a git revision (e.g. HEAD)."""
        rel = self.design_dir.relative_to(self._git_root()).as_posix()
        listing = self._git("ls-tree", "-r", "--name-only", "--full-name", revision, "--", rel)
        files = {}
        for name in listing.splitlines():
            path = DesignPath(name[len(rel) + 1:])
            if codec.node_id(path) is not None:
                files[path] = self._git("show", f"{revision}:{name}")
        return codec.load(files)

    def merge_base(self, revision: Revision) -> Revision:
        """Where the current work diverged from `revision`: what a pull request against it would compare with."""
        return Revision(self._git("merge-base", revision, "HEAD").strip())

    def snapshot_at(self, revision: Revision) -> Snapshot:
        """The sources as committed at `revision`, under today's roots (no history or reports)."""
        roots = self.roots()
        top = self._git_root()
        prefix = self.root.relative_to(top).as_posix()
        prefix = "" if prefix == "." else prefix + "/"
        files: dict[SourcePath, str] = {}
        for base in (*roots.source, *roots.test):
            listing = self._git("ls-tree", "-r", "--name-only", "--full-name", revision, "--", base or ".")
            for name in listing.splitlines():
                rel = name[len(prefix):] if name.startswith(prefix) else name
                if rel.endswith(".py") and not any(p.startswith(".") or p in _SKIP_DIRS for p in rel.split("/")[:-1]):
                    files.setdefault(SourcePath(rel), self._git("show", f"{revision}:{name}"))
        return Snapshot(files, roots)

    def changed_files(self, revision: Revision) -> tuple[FileChange, ...]:
        """Source files that differ from `revision` in the working tree, including new untracked ones."""
        roots = self.roots()
        paths = [r or "." for r in (*roots.source, *roots.test)]
        tracked = parse_numstat(NumStat(self._git("diff", "--numstat", "--relative", revision, "--", *paths)))
        untracked = []
        for name in self._git("ls-files", "--others", "--exclude-standard", "--", *paths).splitlines():
            text = (self.root / name).read_text(encoding="utf-8", errors="replace")
            untracked.append(FileChange(SourcePath(name), LineNo(text.count("\n")), LineNo(0)))
        return tuple(sorted((*tracked, *untracked), key=lambda c: c.path))

    def _git_root(self) -> Path:
        return Path(self._git("rev-parse", "--show-toplevel").strip())

    def _git(self, *args: str) -> str:
        try:
            out = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=False)
        except FileNotFoundError as e:
            raise NoRevision("git is not installed") from e
        if out.returncode != 0:
            raise NoRevision(out.stderr.strip() or f"git {' '.join(args)} failed")
        return out.stdout

    def read_project_file(self, path: ProjectPath) -> SourceText | None:
        full = self.root / path
        return full.read_text(encoding="utf-8") if full.is_file() else None

    def relative(self, path: Path) -> ProjectPath | None:
        """`path` relative to the project root, or None when it lies outside the project."""
        try:
            return ProjectPath(path.resolve().relative_to(self.root).as_posix())
        except ValueError:
            return None

    def write_project(self, edits: Sequence[ProjectEdit]) -> None:
        self._write([(self.root / e.path, e.before, e.after) for e in edits])

    def write(self, design_edits: Sequence[DesignEdit], source_edits: Sequence[SourceEdit]) -> None:
        """Write a batch of edits, all or nothing. Refuses if any file changed since it was read."""
        targets = [(self.design_dir / e.path, e.before, e.after) for e in design_edits]
        targets += [(self.root / e.path, e.before, e.after) for e in source_edits]
        self._write(targets)

    def _write(self, targets: Sequence[tuple[Path, str | None, str | None]]) -> None:
        for path, before, _ in targets:
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != before:
                raise StaleEdit(f"{path.relative_to(self.root)} changed since it was read; run the command again")
        staged: list[tuple[Path, Path]] = []
        try:
            for path, _, after in targets:
                if after is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".arch-tmp")
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(after)
                    staged.append((Path(tmp), path))
        except OSError:
            for tmp, _ in staged:
                tmp.unlink(missing_ok=True)
            raise
        for tmp, path in staged:
            os.replace(tmp, path)
        for path, _, after in targets:
            if after is None:
                path.unlink(missing_ok=True)
                self._prune(path.parent)

    def _prune(self, directory: Path) -> None:
        """Remove directories emptied by deletions, up to the design directory."""
        while directory != self.design_dir and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            directory = directory.parent


def create(start: Path) -> Workspace:
    """A workspace for a project that has no design yet, rooted at `start`."""
    ws = Workspace(start.resolve())
    if any((ws.design_dir / "components").rglob("*.md")):
        raise AlreadyDesigned(f"{ws.design_dir} already has components; arch init only starts new designs")
    return ws


def find(start: Path) -> Workspace:
    """Search upward for `design/` or `arch.toml`, stopping at the repository root."""
    here = start.resolve()
    for d in (here, *here.parents):
        if (d / DESIGN_DIR).is_dir() or (d / CONFIG_FILE).is_file():
            return Workspace(d)
        if (d / ".git").exists():
            break
    raise NoProject(f"no {DESIGN_DIR}/ directory or {CONFIG_FILE} found from {here} up to the repository root")
