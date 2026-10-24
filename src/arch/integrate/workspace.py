"""Load and persist what arch reads and writes in a project.

Realizes arch.integrate.workspace: the only component that touches the filesystem (shell-io).
Hides filesystem layout; the core only ever sees snapshots as data.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from arch import realize
from arch.model import codec
from arch.model.ids import DesignPath
from arch.model.schema import Design
from arch.realize.facts import Facts, Roots, Snapshot, SourcePath

DESIGN_DIR = "design"
CONFIG_FILE = "arch.toml"
_SKIP_DIRS = frozenset({"__pycache__", "node_modules", "venv", "build", "dist", DESIGN_DIR})


class NoProject(Exception):
    pass


class BadConfig(Exception):
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


def find(start: Path) -> Workspace:
    """Search upward for `design/` or `arch.toml`, stopping at the repository root."""
    here = start.resolve()
    for d in (here, *here.parents):
        if (d / DESIGN_DIR).is_dir() or (d / CONFIG_FILE).is_file():
            return Workspace(d)
        if (d / ".git").exists():
            break
    raise NoProject(f"no {DESIGN_DIR}/ directory or {CONFIG_FILE} found from {here} up to the repository root")
