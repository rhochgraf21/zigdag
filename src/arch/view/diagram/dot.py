"""Diagrams as Graphviz `dot`, for SVG and PNG exports (`arch diagram --format dot | dot -Tsvg`).

Part of arch.view.diagram.
"""

from __future__ import annotations

from typing import NewType

from arch.view.diagram.model import Diagram, EdgeKind, EffectClass, Mark, Node

DotText = NewType("DotText", str)

_FILL = {EffectClass.PURE: "#e6f4ea", EffectClass.EFFECTFUL: "#fef7e0", EffectClass.VIOLATING: "#fce8e6",
         EffectClass.UNKNOWN: "#f1f3f4"}
_MARK = {Mark.ADDED: 'color="#1e8e3e" penwidth=2', Mark.REMOVED: 'color="#d93025" style="dashed"',
         Mark.CHANGED: 'color="#1a73e8" penwidth=2', Mark.UNCHANGED: ""}


def _id(cid: str) -> str:
    return '"' + cid + '"'


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _anchor(cid: str) -> str:
    return _id(cid + "#")  # an invisible point inside a cluster, so edges can attach to the box


def render(diagram: Diagram) -> DotText:
    lines = ["digraph arch {", "  rankdir=LR; compound=true; node [shape=box, style=\"rounded,filled\", fillcolor=white];"]
    clusters: set[str] = set()

    def emit(n: Node, indent: str) -> None:
        attrs = " ".join(a for a in (_MARK[n.mark], f'fillcolor="{_FILL[n.effect]}"' if n.effect else "",
                                     'style="rounded,filled,dashed"' if n.status.value == "draft" else "") if a)
        if n.children:
            clusters.add(n.id)
            lines.append(f"{indent}subgraph {_q('cluster_' + n.id)} {{ label={_q(n.label)}; {attrs}")
            lines.append(f"{indent}  {_anchor(n.id)} [shape=point, style=invis, width=0];")
            for c in n.children:
                emit(c, indent + "  ")
            lines.append(f"{indent}}}")
        else:
            lines.append(f"{indent}{_id(n.id)} [label={_q(n.label)} tooltip={_q(n.realizes)} {attrs}];")

    for n in diagram.nodes:
        emit(n, "  ")
    for e in diagram.edges:
        src = _anchor(e.source) if e.source in clusters else _id(e.source)
        dst = _anchor(e.target) if e.target in clusters else _id(e.target)
        attrs = []
        if e.source in clusters:
            attrs.append(f"ltail={_q('cluster_' + e.source)}")
        if e.target in clusters:
            attrs.append(f"lhead={_q('cluster_' + e.target)}")
        if e.kind is EdgeKind.UNDECLARED:
            attrs += ['color="#d93025"', 'label="undeclared"']
        elif e.kind is EdgeKind.HIDDEN:
            attrs += ['color="#b06000"', 'style="dashed"', 'dir="none"', 'label="changed together"']
        if e.mark is not Mark.UNCHANGED and _MARK[e.mark]:
            attrs.append(_MARK[e.mark])
        lines.append(f"  {src} -> {dst}" + (f" [{' '.join(attrs)}]" if attrs else "") + ";")
    lines.append("}")
    return DotText("\n".join(lines))


__all__ = ["DotText", "render"]
