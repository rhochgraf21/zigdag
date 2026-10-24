"""Every user-facing operation, defined once.

Realizes arch.integrate.catalog. Surfaces (CLI now; MCP and agent skills later) are thin layers over
these operations, so they cannot drift apart.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from arch.check import check as run_checks
from arch.check.engine import Report, Severity
from arch.guide.plan import plan as make_plan
from arch.integrate import workspace
from arch.integrate.workspace import Workspace
from arch.model.graph import Graph
from arch.model.matrix import matrix_of
from arch.model.ids import ComponentId
from arch.view import diagram
from arch.view.context import DEFAULT_BUDGET_TOKENS, UnknownTarget
from arch.view.context import context as make_context
from arch.view.outline import outline as make_outline


class UnknownComponent(Exception):
    pass


UsageError = (UnknownComponent, UnknownTarget)


NoProject = (workspace.NoProject, workspace.BadConfig)


def open_project(start: Path) -> Workspace:
    return workspace.find(start)


def _graph(ws: Workspace) -> Graph:
    return Graph(ws.design())


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


def check(ws: Workspace, include_info: bool = False) -> Result:
    report: Report = run_checks(_graph(ws), ws.facts())
    lines = []
    for f in report.findings:
        if f.severity is Severity.INFO and not include_info:
            continue
        where = f" ({f.location})" if f.location else ""
        lines.append(f"{f.severity.value:7} {f.rule} {f.subject}: {f.message}{where}\n        hint: {f.hint}")
    counts = {s: sum(1 for f in report.findings if f.severity is s) for s in Severity}
    hidden = "" if include_info or not counts[Severity.INFO] else " (--all to list info)"
    lines.append(f"{counts[Severity.ERROR]} errors, {counts[Severity.WARNING]} warnings, {counts[Severity.INFO]} info{hidden}")
    data = [
        {"rule": f.rule, "subject": f.subject, "severity": f.severity.value, "message": f.message,
         "hint": f.hint, "location": str(f.location) if f.location else None}
        for f in report.findings
    ]
    return Result("\n".join(lines), data, Outcome.BLOCKING if report.blocking else Outcome.OK)


def context(ws: Workspace, target: str, budget: int = DEFAULT_BUDGET_TOKENS) -> Result:
    g, facts = _graph(ws), ws.facts()
    card = make_context(g, facts, run_checks(g, facts), target, budget)
    return Result(card.to_text(), card.to_json())


def outline(ws: Workspace, root: str | None = None, depth: int | None = None) -> Result:
    g = _graph(ws)
    o = make_outline(g, _component(g, root), depth)
    return Result(o.to_text(), o.to_json())


def matrix(ws: Workspace, parent: str | None = None) -> Result:
    g = _graph(ws)
    targets = [_component(g, parent)] if parent else [c for c in g.ids() if g.children(c)]
    ms = [matrix_of(g, c) for c in targets if c is not None]
    return Result("\n\n".join(diagram.matrix_text(m) for m in ms), [diagram.matrix_json(m) for m in ms])


def plan(ws: Workspace, targets: Sequence[str] = ()) -> Result:
    g = _graph(ws)
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
    Operation("check", "Check the design, and the code against it", False, check),
    Operation("context", "What you need to work on a component or file: intent, port, rules, neighbours", False, context),
    Operation("outline", "Show the decomposition as an outline, in realization order", False, outline),
    Operation("matrix", "Show design matrices (rows use columns)", False, matrix),
    Operation("plan", "Show realization layers, or the impact of changing components", False, plan),
)
