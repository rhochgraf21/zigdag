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
from arch.model import codec
from arch.model.ids import DesignPath
from arch.model.schema import Design
from arch.realize.facts import Facts, Roots, Snapshot, SourcePath

Revision = NewType("Revision", str)  # anything git accepts, e.g. HEAD or a commit id

DESIGN_DIR = "design"
CONFIG_FILE = "arch.toml"
_SKIP_DIRS = frozenset({"__pycache__", "node_modules", "venv", "build", "dist", DESIGN_DIR})


class NoProject(Exception):
    pass


class BadConfig(Exception):
    pass


class StaleEdit(Exception):
    """A file changed on disk since it was read; nothing was written."""


class NoRevision(Exception):
    pass


@dataclass(frozen=True)
class ProjectConfig:
    """What `arch.toml` says; every field optional. Parsed here, at the edge, into typed values."""

    source_roots: tuple[SourcePath, ...] | None = None
    test_roots: tuple[SourcePath, ...] | None = None

    @staticmethod
    def read(path: Path) -> ProjectConfig:
        if not path.is_file():
            return ProjectConfig()
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise BadConfig(f"{path.name}: {e}") from e
        roots = raw.get("roots", {})
        return ProjectConfig(_paths(roots, "source", path), _paths(roots, "tests", path))


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
        return Snapshot(files, roots)

    def facts(self) -> Facts:
        return realize.extract(self.snapshot())

    def read_input(self, path: Path) -> str:
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

    def write(self, design_edits: Sequence[DesignEdit], source_edits: Sequence[SourceEdit]) -> None:
        """Write a batch of edits, all or nothing. Refuses if any file changed since it was read."""
        targets = [(self.design_dir / e.path, e.before, e.after) for e in design_edits]
        targets += [(self.root / e.path, e.before, e.after) for e in source_edits]
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


def find(start: Path) -> Workspace:
    """Search upward for `design/` or `arch.toml`, stopping at the repository root."""
    here = start.resolve()
    for d in (here, *here.parents):
        if (d / DESIGN_DIR).is_dir() or (d / CONFIG_FILE).is_file():
            return Workspace(d)
        if (d / ".git").exists():
            break
    raise NoProject(f"no {DESIGN_DIR}/ directory or {CONFIG_FILE} found from {here} up to the repository root")
