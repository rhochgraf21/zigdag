"""Renaming an FR, with its DP and everything below it, everywhere the name is used (DESIGN2 §9).

Edits are made in place, at the exact positions the names were read from, so comments and layout survive; the
files are then formatted. The log is history and is never rewritten.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from dataclasses import dataclass

from zigdag.core.record import tree as t
from zigdag.core.record.fmt import format_text
from zigdag.core.record.model import Domain
from zigdag.core.record.read import domain_file, domain_of
from zigdag.core.findings import RecordPath
from zigdag.core.names import STATEMENT_SEPARATOR, FrName, subject
from zigdag.core.code import Qualified
from zigdag.core.texts import FileText, Say, Written


@dataclass(frozen=True)
class _Edit:
    line: int  # 1-based
    column: int  # 1-based
    old: str
    new: str


def renamed(name: Written, old: FrName, new: FrName) -> Written | None:
    """The name after the rename, or None when the rename does not touch it."""
    for sep in ("", ".", STATEMENT_SEPARATOR):
        if name == old if not sep else name.startswith(old + sep):
            return new + name[len(old):]
    return None


def _text_edits(node: t.Node, old: FrName, new: FrName, out: list[_Edit]) -> None:
    items = node.items if isinstance(node, t.Seq) else (node,) if isinstance(node, t.Text) else ()
    for item in items:
        if isinstance(item, t.Text) and (n := renamed(item.text, old, new)) is not None:
            out.append(_Edit(item.span.line, item.span.column, item.text, n))


def _subject_edit(node: t.Node, old: FrName, new: FrName, out: list[_Edit]) -> None:
    """A statement of the renamed FR names it by its last part: "the core shall" becomes "the engine shall"."""
    if not isinstance(node, t.Text) or subject(old) == subject(new):
        return
    pattern = re.compile(rf"\b(the) {re.escape(subject(old))} (shall)\b", re.IGNORECASE)
    text = pattern.sub(lambda m: f"{m.group(1)} {subject(new)} {m.group(2)}", node.text, count=1)
    if text != node.text:
        out.append(_Edit(node.span.line, node.span.column, node.text, text))


def _yaml_edits(path: RecordPath, root: t.Map, old: FrName, new: FrName) -> list[_Edit]:
    domain = domain_of(path)
    out: list[_Edit] = []

    def key(entry: t.Entry) -> None:
        if (n := renamed(entry.key, old, new)) is not None:
            out.append(_Edit(entry.key_span.line, entry.key_span.column, entry.key, n))

    def rule(body: t.Node) -> None:
        if not isinstance(body, t.Map):
            return
        if (on := body.get("on")) is not None:
            _text_edits(on.value, old, new, out)
            if isinstance(on.value, t.Text) and on.value.text == old and (st := body.get("statement")) is not None:
                _subject_edit(st.value, old, new, out)
        if (w := body.get("with")) is not None and isinstance(w.value, t.Map):
            for p in w.value:
                if p.key in ("allow", "data"):
                    _text_edits(p.value, old, new, out)

    if domain is Domain.FUNCTIONAL:
        if (frs := root.get("frs")) is not None and isinstance(frs.value, t.Map):
            for e in frs.value:
                key(e)
                statements = e.value.get("statements") if e.key == old and isinstance(e.value, t.Map) else None
                if statements is not None and isinstance(statements.value, t.Map):
                    for s in statements.value:
                        _subject_edit(s.value, old, new, out)
        if (cs := root.get("constraints")) is not None and isinstance(cs.value, t.Map):
            for e in cs.value:
                rule(e.value)
    elif domain is Domain.PHYSICAL:
        for e in root:
            key(e)
    elif domain is Domain.PROCESS:
        for e in root:
            rule(e.value)
    return out


def _apply(text: str, edits: list[_Edit]) -> tuple[str, list[str]]:
    lines = text.split("\n")
    missed = []
    for e in sorted(edits, key=lambda e: (e.line, e.column), reverse=True):
        line = lines[e.line - 1]
        at = e.column - 1
        for quote in ("", '"', "'"):
            if line[at:].startswith(quote + e.old):
                start = at + len(quote)
                lines[e.line - 1] = line[:start] + e.new + line[start + len(e.old):]
                break
        else:
            missed.append(f"line {e.line}: expected {e.old}")
    return "\n".join(lines), missed


def _python_edits(path: RecordPath, text: str, old: FrName, new: FrName) -> list[_Edit]:
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        func = node.func if isinstance(node, ast.Call) else None
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if name != "verifies":
            continue
        for a in node.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str) and (n := renamed(a.value, old, new)):
                out.append(_Edit(a.lineno, a.col_offset + 1, a.value, n))
    return out


def rename(design: Mapping[RecordPath, FileText], tests: Mapping[RecordPath, FileText], old: FrName,
           new: FrName) -> tuple[dict[RecordPath, FileText], list[Say]]:
    """The files the rename changes, as their new text, and any place a name could not be found where it was read."""
    changed: dict[RecordPath, str] = {}
    problems: list[str] = []
    for path, text in sorted(design.items()):
        root, _ = t.read_tree(path, text)
        if not isinstance(root, t.Map):
            continue
        edits = _yaml_edits(path, root, old, new)
        if edits:
            out, missed = _apply(text, edits)
            problems += [f"{path} {m}" for m in missed]
            changed[path] = format_text(path, out)[0] or out
    for path, text in sorted(tests.items()):
        edits = _python_edits(path, text, old, new)
        if edits:
            out, missed = _apply(text, edits)
            problems += [f"{path} {m}" for m in missed]
            changed[path] = out
    return changed, problems


def keep_code(physical: FileText | None, placements: Mapping[FrName, tuple[Qualified, ...]]) -> FileText:
    """physical.yaml with entries added, so renamed DPs keep the code their old names pointed at."""
    text = (physical or "").rstrip("\n")
    lines = [text] if text else []
    lines += [f"{name}: [{', '.join(units)}]" for name, units in sorted(placements.items())]
    path = domain_file(Domain.PHYSICAL)
    joined = "\n".join(lines) + "\n"
    return format_text(path, joined)[0] or joined
