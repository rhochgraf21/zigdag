"""Diagrams as SVG with a layered layout computed here, so positions are deterministic and stable.

Part of arch.view.diagram. Columns follow build order (what is used sits left of what uses it); within a
column, nodes are ordered by id. Colours come from CSS classes, so a page can theme them (light and dark).
"""

from __future__ import annotations

import html
from typing import NewType

from arch.model.ids import ComponentId
from arch.model.matrix import layer
from arch.view.diagram.model import Diagram, EdgeKind, Mark, Node

SvgText = NewType("SvgText", str)

_CHAR = 7.4  # px per character of the label font
_PAD_X, _BOX_H, _GAP_X, _GAP_Y, _MARGIN = 14, 30, 64, 14, 12


def render(diagram: Diagram) -> SvgText:
    nodes = {n.id: n for n in diagram.all_nodes()}
    if not nodes:
        return SvgText('<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0"></svg>')
    deps = {c: sorted({e.target for e in diagram.edges if e.source == c and e.target in nodes}) for c in nodes}
    columns = layer(tuple(nodes), deps.__getitem__).layers
    width = {c: _PAD_X * 2 + _CHAR * len(nodes[c].label) for c in nodes}
    col_w = [max(width[c] for c in col) for col in columns]
    pos: dict[ComponentId, tuple[float, float]] = {}
    x = _MARGIN
    for col, w in zip(columns, col_w):
        for row, c in enumerate(col):
            pos[c] = (x + (w - width[c]) / 2, _MARGIN + row * (_BOX_H + _GAP_Y))
        x += w + _GAP_X
    total_w = x - _GAP_X + _MARGIN
    total_h = _MARGIN * 2 + max(len(col) for col in columns) * (_BOX_H + _GAP_Y) - _GAP_Y

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" class="arch-diagram" viewBox="0 0 {total_w:.0f} {total_h:.0f}" '
             f'width="{total_w:.0f}" height="{total_h:.0f}" role="img" aria-label="{html.escape(diagram.title)}">',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>']
    for e in diagram.edges:
        if e.source not in pos or e.target not in pos:
            continue
        (sx, sy), (tx, ty) = pos[e.source], pos[e.target]
        x1, y1 = sx, sy + _BOX_H / 2  # leave the user's left side...
        x2, y2 = tx + width[e.target], ty + _BOX_H / 2  # ...arrive at the dependency's right side
        if x2 >= x1:  # same column (a cycle): arc around the top
            x2, y2 = tx + width[e.target] / 2, ty
            path = f"M{sx + width[e.source] / 2:.1f},{sy:.1f} C{x1:.1f},{min(sy, ty) - 30:.1f} {x2:.1f},{min(sy, ty) - 30:.1f} {x2:.1f},{y2:.1f}"
        else:
            mid = (x1 + x2) / 2
            path = f"M{x1:.1f},{y1:.1f} C{mid:.1f},{y1:.1f} {mid:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
        classes = " ".join(c for c in ("edge", e.kind.value, e.mark.value if e.mark is not Mark.UNCHANGED else "") if c)
        marker = "" if e.kind is EdgeKind.HIDDEN else ' marker-end="url(#arrow)"'
        title = {EdgeKind.DECLARED: "uses", EdgeKind.UNDECLARED: "imports without declaring it",
                 EdgeKind.HIDDEN: "changed together, no dependency"}[e.kind]
        parts.append(f'<path d="{path}" class="{classes}"{marker}><title>{html.escape(e.source)} {title} '
                     f'{html.escape(e.target)}</title></path>')
    for c, (nx, ny) in sorted(pos.items()):
        parts.append(_box(nodes[c], nx, ny, width[c]))
    parts.append("</svg>")
    return SvgText("".join(parts))


def _box(n: Node, x: float, y: float, w: float) -> str:
    classes = ["node", f"status-{n.status.value}"]
    if n.mark is not Mark.UNCHANGED:
        classes.append(n.mark.value)
    if n.effect is not None:
        classes.append(f"effect-{n.effect.value}")
    return (f'<g class="{" ".join(classes)}" data-component="{html.escape(n.id)}">'
            f'<title>{html.escape(n.id)}: {html.escape(n.realizes)}</title>'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{_BOX_H}" rx="6"/>'
            f'<text x="{x + w / 2:.1f}" y="{y + _BOX_H / 2 + 4:.1f}" text-anchor="middle">{html.escape(n.label)}</text></g>')
