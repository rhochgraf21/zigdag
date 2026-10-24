"""Relate Python code to the design (arch.realize.python): the Python adapter."""

from __future__ import annotations

from arch.realize.facts import Facts, FileSuffix, Language, Role, Roots, SourcePath, SourceText, UnitName
from arch.realize.python import extract as _extract


class PythonAdapter:
    language: Language = _extract.LANGUAGE
    suffixes: tuple[FileSuffix, ...] = (FileSuffix(".py"),)

    def unit_name(self, path: SourcePath, roots: Roots) -> UnitName | None:
        """Module path relative to its source root; test units keep their root's name as a prefix."""
        root = roots.root_of(path)
        if root is None or not path.endswith(".py"):
            return None
        if roots.role_of(path) is Role.TEST:
            root = SourcePath(root.rpartition("/")[0])
        rel = path[len(root):].lstrip("/") if root not in ("", ".") else path
        parts = rel.removesuffix(".py").split("/")
        if parts[-1] == "__init__":
            parts.pop()
        if not parts or not all(p.isidentifier() for p in parts):
            return None
        return UnitName(".".join(parts))

    def extract(self, path: SourcePath, text: SourceText, unit: UnitName, role: Role) -> Facts:
        return _extract.extract(path, text, unit, role)
