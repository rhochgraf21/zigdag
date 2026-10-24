"""Diagrams as Mermaid flowcharts, which GitHub, GitLab and most editors render without installing anything.

Part of arch.view.diagram.
"""

from __future__ import annotations

from typing import NewType

from arch.view.diagram.model import Diagram, EdgeKind, EffectClass, Mark, Node

MermaidText = NewType("MermaidText", str)

_CLASSES = {
    "added": "fill:#e6f4ea,stroke:#1e8e3e,stroke-width:2px",
    "removed": "fill:#fce8e6,stroke:#d93025,stroke-dasharray:4 3",
    "changed": "fill:#e8f0fe,stroke:#1a73e8,stroke-width:2px",
    "pure": "fill:#e6f4ea,stroke:#188038",
    "effectful": "fill:#fef7e0,stroke:#b06000",
    "violating": "fill:#fce8e6,stroke:#d93025,stroke-width:2px",
    "unknown": "fill:#f1f3f4,stroke:#80868b,stroke-dasharray:3 3",
    "draft": "stroke-dasharray:5 4",
}


def _id(cid: str) -> str:
    return "n_" + cid.replace(".", "__").replace("-", "_")


def _label(text: str) -> str:
    return text.replace('"', "#quot;")


def _classes(n: Node) -> list[str]:
    out = []
    if n.mark is not Mark.UNCHANGED:
        out.append(n.mark.value)
    if n.effect is not None:
        out.append(n.effect.value)
    if n.status.value == "draft":
        out.append("draft")
    return out


def render(diagram: Diagram) -> MermaidText:
    lines = ["flowchart LR"]

    def emit(n: Node, indent: str) -> None:
        if n.children:
            lines.append(f'{indent}subgraph {_id(n.id)}["{_label(n.label)}"]')
            for c in n.children:
                emit(c, indent + "  ")
            lines.append(f"{indent}end")
        else:
            lines.append(f'{indent}{_id(n.id)}["{_label(n.label)}"]')

    for n in diagram.nodes:
        emit(n, "  ")
    styles = []
    for i, e in enumerate(diagram.edges):
        arrow = {EdgeKind.DECLARED: "-->", EdgeKind.UNDECLARED: "-->", EdgeKind.HIDDEN: "-.-"}[e.kind]
        label = {EdgeKind.UNDECLARED: "|undeclared|", EdgeKind.HIDDEN: "|changed together|"}.get(e.kind, "")
        lines.append(f"  {_id(e.source)} {arrow}{label} {_id(e.target)}")
        if e.kind is EdgeKind.UNDECLARED or e.mark is Mark.REMOVED:
            styles.append(f"  linkStyle {i} stroke:#d93025,stroke-width:2px" + (",stroke-dasharray:4 3" if e.mark is Mark.REMOVED else ""))
        elif e.kind is EdgeKind.HIDDEN:
            styles.append(f"  linkStyle {i} stroke:#b06000,stroke-dasharray:4 3")
        elif e.mark is Mark.ADDED:
            styles.append(f"  linkStyle {i} stroke:#1e8e3e,stroke-width:2px")
    lines += styles
    used: dict[str, list[str]] = {}
    for n in diagram.all_nodes():
        for c in _classes(n):
            used.setdefault(c, []).append(_id(n.id))
    for name in sorted(used):
        lines.append(f"  classDef {name} {_CLASSES[name]}")
        lines.append(f"  class {','.join(used[name])} {name}")
    return MermaidText("\n".join(lines))


__all__ = ["EffectClass", "MermaidText", "render"]
