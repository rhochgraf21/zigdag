"""Structure, shown in forms that stay stable across revisions.

Realizes arch.view.diagram. For now: the design structure matrix as text. Rows and columns follow
realization order, so a decoupled design reads lower-triangular.
"""

from __future__ import annotations

from arch.model.matrix import Matrix


def matrix_text(m: Matrix, cell: int = 5) -> str:
    names = [c.rsplit(".", 1)[-1] for c in m.order]
    if not names:
        return f"{m.parent}: no children"
    w = max(len(n) for n in names)
    rows = [f"{m.parent}: {m.coupling.value}", " " * (w + 2) + "".join(n[: cell - 1].ljust(cell) for n in names)]
    for row, name in zip(m.order, names):
        marks = ("X" if row == col or (row, col) in m.entries else "·" for col in m.order)
        rows.append(f"{name.ljust(w)}  " + "".join(x.ljust(cell) for x in marks))
    for coupled in m.layering.coupled:
        rows.append("coupled: " + ", ".join(c.rsplit(".", 1)[-1] for c in coupled))
    return "\n".join(r.rstrip() for r in rows)


def matrix_json(m: Matrix) -> dict[str, object]:
    return {
        "parent": m.parent,
        "coupling": m.coupling.value,
        "order": list(m.order),
        "entries": sorted([r, c] for r, c in m.entries),
        "layers": [list(layer) for layer in m.layering.layers],
        "coupled": [list(c) for c in m.layering.coupled],
    }
