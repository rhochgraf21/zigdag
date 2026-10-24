"""Design structure matrices as text, with observations overlaid.

Part of arch.view.diagram. Rows and columns follow realization order, so a decoupled design reads
lower-triangular.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from arch.model.graph import Graph
from arch.model.ids import ComponentId, is_within
from arch.model.matrix import Matrix, matrix_of
from arch.realize.facts import Facts, Role
from arch.realize.history import History
from arch.realize.mapping import map_units
from arch.view.render import Count, JsonValue, Markdown

HIDDEN_COUPLING_MIN_COMMITS = 3


_CELL = 5  # characters per matrix column


def matrix_text(m: Matrix) -> Markdown:
    cell = _CELL
    names = [c.rsplit(".", 1)[-1] for c in m.order]
    if not names:
        return Markdown(f"{m.parent}: no children")
    w = max(len(n) for n in names)
    rows = [f"{m.parent}: {m.coupling.value}", " " * (w + 2) + "".join(n[: cell - 1].ljust(cell) for n in names)]
    for row, name in zip(m.order, names):
        marks = ("X" if row == col or (row, col) in m.entries else "·" for col in m.order)
        rows.append(f"{name.ljust(w)}  " + "".join(x.ljust(cell) for x in marks))
    for coupled in m.layering.coupled:
        rows.append("coupled: " + ", ".join(c.rsplit(".", 1)[-1] for c in coupled))
    return Markdown("\n".join(r.rstrip() for r in rows))


def matrix_json(m: Matrix) -> JsonValue:
    return {
        "parent": m.parent,
        "coupling": m.coupling.value,
        "order": list(m.order),
        "entries": sorted([r, c] for r, c in m.entries),
        "layers": [list(layer) for layer in m.layering.layers],
        "coupled": [list(c) for c in m.layering.coupled],
    }


@dataclass(frozen=True)
class MatrixView:
    matrices: tuple[Matrix, ...]

    def to_markdown(self) -> Markdown:
        return Markdown("\n\n".join(matrix_text(m) for m in self.matrices))

    def to_json(self) -> JsonValue:
        return [matrix_json(m) for m in self.matrices]


class Observed(enum.Enum):
    """What a matrix cell shows when observations are overlaid on declared uses."""

    DECLARED = "X"
    UNDECLARED_IMPORT = "!"  # the code imports it, the design does not say so
    HIDDEN = "~"  # changed together repeatedly, with no dependency either way
    NONE = "·"


@dataclass(frozen=True)
class ObservedMatrix:
    matrix: Matrix
    cells: dict[tuple[ComponentId, ComponentId], Observed]
    together: dict[tuple[ComponentId, ComponentId], Count]

    def to_markdown(self) -> Markdown:
        m = self.matrix
        names = [c.rsplit(".", 1)[-1] for c in m.order]
        if not names:
            return Markdown(f"{m.parent}: no children")
        w = max(len(n) for n in names)
        rows = [f"{m.parent}: {m.coupling.value}  (X declared, ! undeclared import, ~ changed together "
                f"{HIDDEN_COUPLING_MIN_COMMITS}+ times without a dependency)",
                " " * (w + 2) + "".join(n[:4].ljust(5) for n in names)]
        for row, name in zip(m.order, names):
            marks = ("X" if row == col else self.cells.get((row, col), Observed.NONE).value for col in m.order)
            rows.append(f"{name.ljust(w)}  " + "".join(x.ljust(5) for x in marks))
        return Markdown("\n".join(r.rstrip() for r in rows))

    def to_json(self) -> JsonValue:
        return {**matrix_json(self.matrix),
                "observed": sorted([r, c, v.value] for (r, c), v in self.cells.items()),
                "changed_together": sorted([r, c, n] for (r, c), n in self.together.items())}


def observed_matrix(graph: Graph, parent: ComponentId, facts: Facts) -> ObservedMatrix:
    m = matrix_of(graph, parent)
    units = map_units(graph, facts)
    owner = {u: next((k for k in m.order if is_within(c, k)), None) for u, c in units.component_of.items()}
    cells: dict[tuple[ComponentId, ComponentId], Observed] = {e: Observed.DECLARED for e in m.entries}
    source = {u.name for u in facts.units if u.role is Role.SOURCE}
    for imp in facts.imports:
        target = units.target_of(imp)
        a, b = owner.get(imp.unit), owner.get(target) if target else None
        if imp.unit in source and a and b and a != b and (a, b) not in cells:
            cells[(a, b)] = Observed.UNDECLARED_IMPORT
    history = History.of(facts)
    members = {k: [u for u, o in owner.items() if o == k] for k in m.order}
    together = {}
    for i, a in enumerate(m.order):
        for b in m.order[i + 1:]:
            n = history.co_changes(members[a], members[b])
            if n:
                together[(a, b)] = Count(n)
            if n >= HIDDEN_COUPLING_MIN_COMMITS and (a, b) not in cells and (b, a) not in cells:
                cells[(a, b)] = cells[(b, a)] = Observed.HIDDEN
    return ObservedMatrix(m, cells, together)


@dataclass(frozen=True)
class ObservedMatrixView:
    matrices: tuple[ObservedMatrix, ...]

    def to_markdown(self) -> Markdown:
        return Markdown("\n\n".join(m.to_markdown() for m in self.matrices))

    def to_json(self) -> JsonValue:
        return [m.to_json() for m in self.matrices]
