"""Load and persist what arch reads and writes in a project.

Realizes arch.integrate.workspace: the only component that touches the filesystem (shell-io).
Hides filesystem layout; the core only ever sees snapshots as data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from arch.model import codec
from arch.model.graph import Graph
from arch.model.schema import DesignPath

DESIGN_DIR = "design"
CONFIG_FILE = "arch.toml"


class NoProject(Exception):
    pass


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

    def graph(self) -> Graph:
        return Graph(codec.load(self.design_files()))


def find(start: Path) -> Workspace:
    """Search upward for `design/` or `arch.toml`, stopping at the repository root."""
    here = start.resolve()
    for d in (here, *here.parents):
        if (d / DESIGN_DIR).is_dir() or (d / CONFIG_FILE).is_file():
            return Workspace(d)
        if (d / ".git").exists():
            break
    raise NoProject(f"no {DESIGN_DIR}/ directory or {CONFIG_FILE} found from {here} up to the repository root")
