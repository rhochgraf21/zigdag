"""The one canonical layout of a design file (DESIGN2 §7.2), keeping every value and every comment.

The layout:
- two spaces per level; fields in a fixed order; FRs and physical entries in tree order (each parent before its
  children, siblings as written), everything else in the order written;
- a blank line between the entries of the file and of its sections, when those entries are mappings;
- short lists of text without comments inline (`[a, b]`), everything else as a block;
- values plain where YAML allows it, double-quoted where it does not;
- each comment directly above, or beside, what it was written with. Comments after the last entry go last.
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from zigdag.core.findings import Finding, RecordPath
from zigdag.core.record import tree as t
from zigdag.core.record.comments import Comments, scan
from zigdag.core.record.model import Domain
from zigdag.core.record.read import domain_of

FLOW_WIDTH = 100
_INDICATORS = frozenset("-?:,[]{}#&*!|>'\"%@`")
_FLOW_UNSAFE = frozenset(",[]{}")
_ANY = "*"

_FIELDS: Mapping[tuple[Domain, tuple[str, ...]], tuple[str, ...]] = {
    (Domain.FUNCTIONAL, ()): ("frs", "constraints"),
    (Domain.FUNCTIONAL, ("frs", _ANY)): ("serves", "statements"),
    (Domain.FUNCTIONAL, ("constraints", _ANY)): ("on", "serves", "check", "with", "except", "statement", "off"),
    (Domain.CUSTOMER, (_ANY,)): ("job", "performer", "outcomes"),
    (Domain.PROCESS, (_ANY,)): ("kind", "on", "serves", "check", "with", "except", "evidence", "measures", "report",
                                "step", "produces", "gate", "off"),
}
_TREE_ORDER = frozenset({(Domain.FUNCTIONAL, ("frs",)), (Domain.PHYSICAL, ())})


def _tree_ordered(entries: list[t.Entry]) -> list[t.Entry]:
    """Each parent before its children; siblings, and names whose parent is missing, in the order written."""
    names = {e.key for e in entries}
    children: dict[str, list[t.Entry]] = {}
    roots: list[t.Entry] = []
    for e in entries:
        head, dot, _ = e.key.rpartition(".")
        (children.setdefault(head, []) if dot and head in names else roots).append(e)
    out: list[t.Entry] = []

    def visit(e: t.Entry) -> None:
        out.append(e)
        for child in children.get(e.key, ()):
            visit(child)

    for e in roots:
        visit(e)
    return out


def _matches(pattern: tuple[str, ...], path: tuple[str, ...]) -> bool:
    return len(pattern) == len(path) and all(p in (_ANY, k) for p, k in zip(pattern, path))


def _plain(text: str, flow: bool) -> bool:
    if not text or text != text.strip() or text[0] in _INDICATORS or "\n" in text or "\t" in text:
        return False
    if ": " in text or text.endswith(":") or " #" in text:
        return False
    return not (flow and any(c in _FLOW_UNSAFE for c in text))


def _scalar(text: str, flow: bool = False) -> str:
    return text if _plain(text, flow) else json.dumps(text, ensure_ascii=False)


def _comment(text: str) -> str:
    return f"# {text}" if text else "#"


def _anchor_lines(node: t.Node) -> list[int]:
    """The 0-based lines where entries and list items start: whole-line comments attach to the next of these."""
    out: list[int] = []
    if isinstance(node, t.Map):
        for e in node:
            out.append(e.key_span.line - 1)
            out += _anchor_lines(e.value)
    elif isinstance(node, t.Seq):
        for item in node.items:
            out.append(item.span.line - 1)
            out += _anchor_lines(item)
    return out


@dataclass
class _Writer:
    domain: Domain | None
    comments: Comments
    above: Mapping[int, list[str]]
    out: list[str] = field(default_factory=list)
    used: set[tuple[str, int]] = field(default_factory=set)

    def _above(self, line: int, indent: int) -> None:
        if ("above", line) not in self.used:
            self.used.add(("above", line))
            self.out += [" " * indent + _comment(c) for c in self.above.get(line, ())]

    def _beside(self, *lines: int) -> str:
        for line in lines:
            if line in self.comments.beside and ("beside", line) not in self.used:
                self.used.add(("beside", line))
                return "  " + _comment(self.comments.beside[line])
        return ""

    def _ordered(self, node: t.Map, path: tuple[str, ...]) -> list[t.Entry]:
        entries = list(node.entries)
        if (self.domain, path) in _TREE_ORDER:
            entries = _tree_ordered(entries)
        fields = next((v for (d, p), v in _FIELDS.items() if d is self.domain and _matches(p, path)), None)
        if fields:
            entries.sort(key=lambda e: fields.index(e.key) if e.key in fields else len(fields))
        return entries

    def _flow(self, seq: t.Seq, key_line: int, width: int) -> str | None:
        """The list inline, or None when it must be a block: items with comments, or too long."""
        if not all(isinstance(i, t.Text) for i in seq.items):
            return None
        for item in seq.items:
            line = item.span.line - 1
            if line != key_line and (line in self.above or line in self.comments.beside):
                return None
        text = "[" + ", ".join(_scalar(i.text, flow=True) if i.text else '""' for i in seq.items) + "]"
        return text if width + len(text) <= FLOW_WIDTH else None

    def map(self, node: t.Map, indent: int, path: tuple[str, ...]) -> None:
        entries = self._ordered(node, path)
        blank = len(path) <= 1 and len(entries) > 1 and all(isinstance(e.value, t.Map) for e in entries) and any(
            e.value.entries for e in entries)
        pad = " " * indent
        for i, e in enumerate(entries):
            if blank and i:
                self.out.append("")
            line = e.key_span.line - 1
            self._above(line, indent)
            key = _scalar(e.key)
            v = e.value
            if isinstance(v, t.Text):
                value = f" {_scalar(v.text)}" if v.text else ""
                # An empty value has no line of its own: YAML reports the next line, which is not this entry's.
                beside = self._beside(line, v.span.line - 1) if v.text else self._beside(line)
                self.out.append(f"{pad}{key}:{value}{beside}")
            elif isinstance(v, t.Map):
                if not v.entries:
                    self.out.append(f"{pad}{key}: {{}}{self._beside(line)}")
                else:
                    self.out.append(f"{pad}{key}:{self._beside(line)}")
                    self.map(v, indent + 2, (*path, e.key))
            else:
                flow = self._flow(v, line, len(pad) + len(key) + 2)
                if flow is not None:
                    self.out.append(f"{pad}{key}: {flow}{self._beside(line)}")
                else:
                    self.out.append(f"{pad}{key}:{self._beside(line)}")
                    self.seq(v, indent + 2, (*path, e.key))

    def seq(self, node: t.Seq, indent: int, path: tuple[str, ...]) -> None:
        pad = " " * indent
        for item in node.items:
            line = item.span.line - 1
            self._above(line, indent)
            beside = self._beside(line)
            if isinstance(item, t.Text):
                self.out.append(f"{pad}- {_scalar(item.text) if item.text else chr(34) * 2}{beside}")
            elif isinstance(item, t.Map) and item.entries:
                start = len(self.out)
                self.map(item, indent + 2, (*path, _ANY))
                self.out[start] = f"{pad}- {self.out[start].lstrip()}{beside}"
            elif isinstance(item, t.Map):
                self.out.append(f"{pad}- {{}}{beside}")
            else:
                self.out.append(f"{pad}-{beside}")
                self.seq(item, indent + 2, path)


def format_text(path: RecordPath, text: str) -> tuple[str | None, tuple[Finding, ...]]:
    """The file in its canonical layout, or None (with the reasons) when it cannot be read."""
    root, problems = t.read_tree(path, text)
    if root is None:
        return None, problems
    comments = scan(text)
    anchors = sorted(set(_anchor_lines(root)))
    above: dict[int, list[str]] = {}
    trailing: list[str] = []
    for line in sorted(comments.whole):
        at = bisect.bisect_right(anchors, line)
        if at < len(anchors):
            above.setdefault(anchors[at], []).append(comments.whole[line])
        else:
            trailing.append(comments.whole[line])
    writer = _Writer(domain_of(path), comments, above)
    if isinstance(root, t.Map):
        writer.map(root, 0, ())
    elif isinstance(root, t.Seq):
        writer.seq(root, 0, ())
    else:
        writer.out.append(_scalar(root.text))
    leftover = [comments.beside[n] for n in sorted(comments.beside) if ("beside", n) not in writer.used]
    tail = [_comment(c) for c in trailing + leftover]
    lines = writer.out + ([""] if writer.out and tail else []) + tail
    return ("\n".join(lines) + "\n" if lines else ""), ()


def content(path: RecordPath, text: str) -> tuple[object, tuple[str, ...]] | None:
    """What a file says, ignoring layout: its values (maps compared without order) and all its comment texts."""
    root, _ = t.read_tree(path, text)
    if root is None:
        return None
    comments = scan(text)
    return _values(root), tuple(sorted([*comments.whole.values(), *comments.beside.values()]))


def _values(node: t.Node) -> object:
    if isinstance(node, t.Map):
        return frozenset((e.key, _values(e.value)) for e in node)
    if isinstance(node, t.Seq):
        return tuple(_values(i) for i in node.items)
    return node.text
