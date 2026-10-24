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


_PAIR_W, _PAIR_H, _PAIR_GAP_X, _PAIR_GAP_Y = 200, 52, 56, 16
_FR_CHARS = 30


def render_pair(before: Diagram, after: Diagram) -> tuple[SvgText, SvgText]:
    """Two diagrams laid out on the same grid (over the union of their nodes and edges), so every component
    sits in the same place in both. A node missing on one side is drawn there as a faint ghost."""
    nodes = {n.id: n for n in (*before.all_nodes(), *after.all_nodes())}
    if not nodes:
        empty = SvgText('<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0"></svg>')
        return empty, empty
    edges = {(e.source, e.target) for e in (*before.edges, *after.edges) if e.source in nodes and e.target in nodes}
    deps = {c: sorted(t for s, t in edges if s == c) for c in nodes}
    columns = layer(tuple(nodes), deps.__getitem__).layers
    pos = {c: (_MARGIN + i * (_PAIR_W + _PAIR_GAP_X), _MARGIN + 16 + j * (_PAIR_H + _PAIR_GAP_Y))
           for i, col in enumerate(columns) for j, c in enumerate(col)}
    width = _MARGIN * 2 + len(columns) * (_PAIR_W + _PAIR_GAP_X) - _PAIR_GAP_X
    height = _MARGIN * 2 + 16 + max(len(col) for col in columns) * (_PAIR_H + _PAIR_GAP_Y) - _PAIR_GAP_Y
    return _side(before, nodes, pos, width, height), _side(after, nodes, pos, width, height)


def _side(d: Diagram, union: dict[ComponentId, Node], pos: dict[ComponentId, tuple[float, float]],
          width: float, height: float) -> SvgText:
    present = {n.id: n for n in d.all_nodes()}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" class="arch-diagram pair" viewBox="0 0 {width:.0f} {height:.0f}" '
             f'width="{width:.0f}" height="{height:.0f}" role="img" aria-label="{html.escape(d.title)}">',
             '<defs><marker id="arrow-p" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>']
    for e in d.edges:
        if e.source not in pos or e.target not in pos:
            continue
        (sx, sy), (tx, ty) = pos[e.source], pos[e.target]
        if tx < sx:
            x1, y1, x2, y2 = sx, sy + _PAIR_H / 2, tx + _PAIR_W, ty + _PAIR_H / 2
            mid = (x1 + x2) / 2
            path = f"M{x1:.1f},{y1:.1f} C{mid:.1f},{y1:.1f} {mid:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"
        else:  # same column: arc around the top
            x1, y1, x2, y2 = sx + _PAIR_W / 2, sy, tx + _PAIR_W / 2, ty
            path = f"M{x1:.1f},{y1:.1f} C{x1 + 40:.1f},{min(sy, ty) - 26:.1f} {x2 + 40:.1f},{min(sy, ty) - 26:.1f} {x2:.1f},{y2:.1f}"
        mark = f" {e.mark.value}" if e.mark is not Mark.UNCHANGED else ""
        parts.append(f'<path d="{path}" class="edge{mark}" marker-end="url(#arrow-p)"><title>{html.escape(e.source)} uses '
                     f'{html.escape(e.target)}</title></path>')
    for c, (x, y) in sorted(pos.items()):
        n = present.get(c)
        ghost = n is None
        node = n or union[c]
        classes = ["node", "ghost" if ghost else "", node.mark.value if not ghost and node.mark is not Mark.UNCHANGED else ""]
        fr = node.realizes if len(node.realizes) <= _FR_CHARS else node.realizes[: _FR_CHARS - 1] + "…"
        parts.append(f'<g class="{" ".join(x for x in classes if x)}" data-component="{html.escape(c)}">'
                     f'<title>{html.escape(c)}: {html.escape(node.realizes)}</title>'
                     f'<rect x="{x}" y="{y}" width="{_PAIR_W}" height="{_PAIR_H}" rx="9"/>'
                     f'<text class="name" x="{x + 12}" y="{y + 21}">{html.escape(node.label)}</text>'
                     f'<text class="fr" x="{x + 12}" y="{y + 39}">{html.escape(fr)}</text></g>')
    parts.append("</svg>")
    return SvgText("".join(parts))
