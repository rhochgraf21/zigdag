"""The decomposition as a readable outline.

Realizes arch.view.outline. Siblings appear in realization order, so reading top-down follows
dependency order.
"""

from __future__ import annotations

from dataclasses import dataclass

from arch.model.graph import Graph
from arch.model.matrix import matrix_of
from arch.model.ids import ComponentId, Text
from arch.model.schema import Status


@dataclass(frozen=True)
class OutlineLine:
    id: ComponentId
    depth: int
    realizes: Text
    status: Status
    prefix: str  # tree-drawing characters for text output


@dataclass(frozen=True)
class Outline:
    lines: tuple[OutlineLine, ...]

    def to_text(self, width: int = 100) -> str:
        out = []
        for line in self.lines:
            name = line.id.rsplit(".", 1)[-1] if line.depth else line.id
            head = f"{line.prefix}{name}"
            tag = "" if line.status is Status.SPECIFIED else f" [{line.status.value}]"
            room = max(20, width - len(head) - len(tag) - 4)
            text = line.realizes if len(line.realizes) <= room else line.realizes[: room - 1] + "…"
            out.append(f"{head}{tag}  —  {text}")
        return "\n".join(out)

    def to_json(self) -> list[dict[str, object]]:
        return [
            {"id": l.id, "depth": l.depth, "realizes": l.realizes, "status": l.status.value} for l in self.lines
        ]


def outline(graph: Graph, root: ComponentId | None = None, depth: int | None = None) -> Outline:
    lines: list[OutlineLine] = []

    def walk(cid: ComponentId, level: int, indent: str, branch: str) -> None:
        c = graph[cid]
        lines.append(OutlineLine(cid, level, c.realizes, c.status, indent + branch))
        if depth is not None and level >= depth:
            return
        kids = matrix_of(graph, cid).order
        child_indent = indent + ("" if level == 0 else ("   " if branch == "└─ " else "│  "))
        for i, kid in enumerate(kids):
            walk(kid, level + 1, child_indent, "└─ " if i == len(kids) - 1 else "├─ ")

    for r in (root,) if root else graph.roots:
        walk(r, 0, "", "")
    return Outline(tuple(lines))
