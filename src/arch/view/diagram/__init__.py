"""Structure, shown in forms that stay stable across revisions (arch.view.diagram).

A renderer-neutral diagram model (containment with transitive reduction, effects, observed coupling,
changes) rendered to Mermaid for pull requests and Markdown, and to Graphviz for exports; plus design
structure matrices as text.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from arch.view.diagram import dot, mermaid, svg
from arch.view.diagram.matrix import (
    MatrixView,
    ObservedMatrix,
    ObservedMatrixView,
    Observed,
    matrix_json,
    matrix_text,
    observed_matrix,
)
from arch.view.diagram.model import (
    Diagram,
    Edge,
    EdgeKind,
    Edges,
    EffectClass,
    Mark,
    Node,
    changes,
    containment,
    with_effects,
    with_observed,
)
from arch.view.render import JsonValue, Markdown


class DiagramFormat(enum.Enum):
    MARKDOWN = "markdown"  # a fenced Mermaid block, ready to paste into a PR or a doc
    MERMAID = "mermaid"
    DOT = "dot"
    SVG = "svg"  # laid out by arch itself: deterministic positions


@dataclass(frozen=True)
class DiagramView:
    diagram: Diagram
    format: DiagramFormat = DiagramFormat.MARKDOWN

    def to_markdown(self) -> Markdown:
        if self.format is DiagramFormat.DOT:
            return Markdown(dot.render(self.diagram))
        if self.format is DiagramFormat.SVG:
            return Markdown(svg.render(self.diagram))
        text = mermaid.render(self.diagram)
        return Markdown(text if self.format is DiagramFormat.MERMAID else f"```mermaid\n{text}\n```")

    def to_json(self) -> JsonValue:
        d = self.diagram

        def node(n: Node) -> JsonValue:
            return {"id": n.id, "label": n.label, "realizes": n.realizes, "status": n.status.value,
                    "mark": n.mark.value, "effect": n.effect.value if n.effect else None,
                    "children": [node(c) for c in n.children]}

        return {"title": d.title, "nodes": [node(n) for n in d.nodes],
                "edges": [{"from": e.source, "to": e.target, "kind": e.kind.value, "mark": e.mark.value} for e in d.edges]}


__all__ = [
    "svg", "Diagram", "DiagramFormat", "DiagramView", "Edge", "EdgeKind", "Edges", "EffectClass", "Mark", "MatrixView", "Node",
    "Observed", "ObservedMatrix", "ObservedMatrixView", "changes", "containment", "matrix_json", "matrix_text",
    "observed_matrix", "with_effects", "with_observed",
]
