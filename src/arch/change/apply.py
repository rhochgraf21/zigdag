"""Apply a batch of operations to a design: all or nothing, with the file edits as data.

Realizes arch.change.apply. Hides the transaction: a Draft holds working copies of the files, each
operation changes it, and the result is checked. A batch is rejected if an operation's precondition
fails or if it introduces new integrity problems; quality findings are reported, not blocking.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass

from arch.check import check
from arch.check.engine import Report
from arch.change.ops import Operation, Rejected
from arch.model import codec
from arch.model.codec import NodeFile
from arch.model.graph import Graph
from arch.model.ids import DesignPath, Text
from arch.model.schema import Design, Kind, SourceText
from arch.realize.facts import DesignLink, Snapshot, SourcePath

INTEGRITY_RULES = frozenset({"S000", "S001", "S011"})  # problems that make the design unusable


class Outcome(enum.Enum):
    APPLIED = "applied"
    REJECTED = "rejected"


@dataclass(frozen=True)
class DesignEdit:
    path: DesignPath
    before: SourceText | None  # None: created
    after: SourceText | None  # None: deleted


@dataclass(frozen=True)
class SourceEdit:
    path: SourcePath
    before: SourceText
    after: SourceText


@dataclass(frozen=True)
class ApplyResult:
    outcome: Outcome
    operations: tuple[Operation, ...]
    before: Design
    after: Design
    design_edits: tuple[DesignEdit, ...]
    source_edits: tuple[SourceEdit, ...]
    new_findings: Report  # findings the batch introduces, judged against the design they belong to
    notes: tuple[Text, ...]
    reason: Text | None = None  # why it was rejected


class _Draft:
    """The working copy operations act on (implements arch.change.ops.Draft)."""

    def __init__(self, design: Design, snapshot: Snapshot | None, links: Sequence[DesignLink]):
        self._files: dict[DesignPath, SourceText] = dict(design.sources)
        self._code: dict[SourcePath, SourceText] = dict(snapshot.files) if snapshot else {}
        self._links = list(links)
        self._design: Design | None = design
        self._graph: Graph | None = None
        self.notes: list[Text] = []

    def design(self) -> Design:
        if self._design is None:
            self._design = codec.load(self._files)
        return self._design

    def graph(self) -> Graph:
        if self._graph is None:
            self._graph = Graph(self.design())
        return self._graph

    def _changed(self) -> None:
        self._design, self._graph = None, None

    def exists(self, kind: Kind, ident: Text) -> bool:
        return codec.path_of(kind, ident) in self._files

    def file(self, kind: Kind, ident: Text) -> NodeFile:
        return NodeFile(kind, self._files[codec.path_of(kind, ident)])

    def put(self, kind: Kind, ident: Text, node: NodeFile) -> None:
        self._files[codec.path_of(kind, ident)] = node.text
        self._changed()

    def delete(self, kind: Kind, ident: Text) -> None:
        self._files.pop(codec.path_of(kind, ident), None)
        self._changed()

    def rename(self, kind: Kind, old: Text, new: Text) -> None:
        self._files[codec.path_of(kind, new)] = self._files.pop(codec.path_of(kind, old))
        self._changed()

    def links(self) -> Sequence[DesignLink]:
        return tuple(self._links)

    def rewrite_link(self, link: DesignLink, target: Text) -> None:
        text = self._code.get(link.location.path)
        if text is None:
            self.notes.append(Text(f"could not rewrite {link.target} at {link.location}: file not in snapshot"))
            return
        lines = text.split("\n")
        i = link.location.line - 1
        for quote in ('"', "'"):
            old = f"{quote}{link.target}{quote}"
            if 0 <= i < len(lines) and old in lines[i]:
                lines[i] = lines[i].replace(old, f"{quote}{target}{quote}", 1)
                self._code[link.location.path] = "\n".join(lines)
                return
        self.notes.append(Text(f"could not find {link.target} at {link.location}; update it by hand"))

    def note(self, text: Text) -> None:
        self.notes.append(text)

    def edits(self, before: Design, snapshot: Snapshot | None) -> tuple[tuple[DesignEdit, ...], tuple[SourceEdit, ...]]:
        old = before.sources
        design = tuple(
            DesignEdit(p, old.get(p), self._files.get(p))
            for p in sorted(set(old) | set(self._files))
            if old.get(p) != self._files.get(p)
        )
        original = snapshot.files if snapshot else {}
        source = tuple(SourceEdit(p, original[p], t) for p, t in sorted(self._code.items()) if original.get(p) != t)
        return design, source


def apply(
    design: Design,
    operations: Sequence[Operation],
    snapshot: Snapshot | None = None,
    links: Sequence[DesignLink] = (),
) -> ApplyResult:
    draft = _Draft(design, snapshot, links)
    ops = tuple(operations)

    def rejected(reason: str) -> ApplyResult:
        return ApplyResult(Outcome.REJECTED, ops, design, design, (), (), Report((), Graph(design)), tuple(draft.notes),
                           Text(reason))

    for i, op in enumerate(ops):
        try:
            op.apply_to(draft)
        except (Rejected, ValueError) as e:  # ValueError: a file the operation needs does not parse
            return rejected(f"operation {i + 1} ({op.describe()}): {e}")

    after = draft.design()
    known = {f.identity for f in check(Graph(design)).findings}
    after_graph = Graph(after)
    new = tuple(f for f in check(after_graph).findings if f.identity not in known)
    broken = [f for f in new if f.rule in INTEGRITY_RULES]
    if broken:
        first = broken[0]
        return ApplyResult(Outcome.REJECTED, ops, design, design, (), (), Report(tuple(broken), after_graph), tuple(draft.notes),
                           Text(f"the result would be broken: {first.subject}: {first.message}"))
    design_edits, source_edits = draft.edits(design, snapshot)
    return ApplyResult(Outcome.APPLIED, ops, design, after, design_edits, source_edits, Report(new, after_graph),
                       tuple(draft.notes))
