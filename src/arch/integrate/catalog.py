"""Every user-facing operation, defined once.

Realizes arch.integrate.catalog. Surfaces (CLI now; MCP and agent skills later) are thin layers over
these operations, so they cannot drift apart.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from arch.check import check as run_checks
from arch.check.engine import Report, Severity
from arch.guide.plan import plan as make_plan
from arch.integrate.workspace import Workspace
from arch.model.matrix import matrix_of
from arch.model.schema import ComponentId
from arch.view import diagram
from arch.view.outline import outline as make_outline


class UnknownComponent(Exception):
    pass


class Outcome(enum.Enum):
    OK = 0
    BLOCKING = 1


@dataclass(frozen=True)
class Result:
    text: str
    data: object
    outcome: Outcome = Outcome.OK


@dataclass(frozen=True)
class Operation:
    name: str
    summary: str
    writes_design: bool
    run: Callable[..., Result]


def _component(ws_graph, cid: str | None) -> ComponentId | None:
    if cid is None:
        return None
    if cid not in ws_graph:
        raise UnknownComponent(f"no component '{cid}'")
    return ComponentId(cid)


def check(ws: Workspace) -> Result:
    report: Report = run_checks(ws.graph())
    lines = []
    for f in report.findings:
        where = f" ({f.location})" if f.location else ""
        lines.append(f"{f.severity.value:7} {f.rule} {f.subject}: {f.message}{where}\n        hint: {f.hint}")
    counts = {s: sum(1 for f in report.findings if f.severity is s) for s in Severity}
    lines.append(f"{counts[Severity.ERROR]} errors, {counts[Severity.WARNING]} warnings, {counts[Severity.INFO]} info")
    data = [
        {"rule": f.rule, "subject": f.subject, "severity": f.severity.value, "message": f.message,
         "hint": f.hint, "location": str(f.location) if f.location else None}
        for f in report.findings
    ]
    return Result("\n".join(lines), data, Outcome.BLOCKING if report.blocking else Outcome.OK)


def outline(ws: Workspace, root: str | None = None, depth: int | None = None) -> Result:
    g = ws.graph()
    o = make_outline(g, _component(g, root), depth)
    return Result(o.to_text(), o.to_json())


def matrix(ws: Workspace, parent: str | None = None) -> Result:
    g = ws.graph()
    targets = [_component(g, parent)] if parent else [c for c in g.ids() if g.children(c)]
    ms = [matrix_of(g, c) for c in targets if c is not None]
    return Result("\n\n".join(diagram.matrix_text(m) for m in ms), [diagram.matrix_json(m) for m in ms])


def plan(ws: Workspace, targets: Sequence[str] = ()) -> Result:
    g = ws.graph()
    p = make_plan(g, [c for t in targets if (c := _component(g, t)) is not None])
    short = lambda c: c.split(".", 1)[1] if "." in c else c  # noqa: E731
    lines = [f"L{i}  " + " · ".join(short(c) for c in layer) for i, layer in enumerate(p.layering.layers)]
    if p.targets:
        lines.insert(0, f"targets: {', '.join(p.targets)}\nimpacted: {', '.join(p.impacted) or 'nothing else'}\n")
    for coupled in p.layering.coupled:
        lines.append("coupled (must change together): " + ", ".join(coupled))
    data = {"targets": list(p.targets), "impacted": list(p.impacted),
            "layers": [list(l) for l in p.layering.layers], "coupled": [list(c) for c in p.layering.coupled]}
    return Result("\n".join(lines), data)


OPERATIONS: tuple[Operation, ...] = (
    Operation("check", "Check the design for structural defects", False, check),
    Operation("outline", "Show the decomposition as an outline, in realization order", False, outline),
    Operation("matrix", "Show design matrices (rows use columns)", False, matrix),
    Operation("plan", "Show realization layers, or the impact of changing components", False, plan),
)
