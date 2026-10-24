"""Every catalog operation as an MCP tool, over stdio.

Realizes arch.integrate.mcp: a parse boundary like the CLI. Each tool takes plain JSON arguments, turns
them into domain types, runs the catalog operation and returns its Markdown. Requires the optional
`mcp` extra (`pip install 'arch-design[mcp]'`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from arch.change import ops
from arch.integrate import catalog
from arch.integrate.catalog import (
    Command,
    ContextTarget,
    DiagramFormat,
    Depth,
    Edges,
    MatrixOverlay,
    Overlay,
    Revision,
    TokenBudget,
)
from arch.model.ids import ComponentId, Text
from arch.view.report import EditMode, InfoFindings

INSTRUCTIONS = (
    "arch keeps this project's design in design/. Before editing a file, call `context` with its path. "
    "Change the design only with `edit` (dry_run first). After changes, call `check`. `next` lists what to do."
)


def _tools(project: Path) -> Mapping[Command, Callable[..., str]]:
    def ws() -> catalog.Workspace:
        return catalog.open_project(project)

    def text(result: catalog.Result) -> str:
        return str(result.view.to_markdown())

    def check(all_findings: bool = False) -> str:
        return text(catalog.check(ws(), InfoFindings.LISTED if all_findings else InfoFindings.COUNTED))

    def context(target: str, budget: int = 4000) -> str:
        return text(catalog.context(ws(), ContextTarget(target), TokenBudget(budget)))

    def outline(root: str | None = None, depth: int | None = None) -> str:
        return text(catalog.outline(ws(), ComponentId(root) if root else None, Depth(depth) if depth is not None else None))

    def matrix(parent: str | None = None, observed: bool = False) -> str:
        overlay = MatrixOverlay.OBSERVED if observed else MatrixOverlay.DECLARED_ONLY
        return text(catalog.matrix(ws(), ComponentId(parent) if parent else None, overlay))

    def diagram(component: str | None = None, depth: int = 1, all_edges: bool = False, effects: bool = False,
                observed: bool = False, diff: str | None = None, format: str = "markdown") -> str:
        overlays = frozenset(o for o, on in ((Overlay.EFFECTS, effects), (Overlay.OBSERVED, observed)) if on)
        return text(catalog.diagram(ws(), ComponentId(component) if component else None, Depth(depth),
                                    Edges.ALL if all_edges else Edges.REDUCED, overlays,
                                    Revision(diff) if diff else None, DiagramFormat(format)))

    def plan(targets: list[str] | None = None) -> str:
        return text(catalog.plan(ws(), [ComponentId(t) for t in targets or []]))

    def next_(scope: str | None = None, limit: int = 10) -> str:
        return text(catalog.next_(ws(), ComponentId(scope) if scope else None, catalog.ActionLimit(limit)))

    def edit(operations: list[dict[str, Any]], dry_run: bool = False) -> str:
        """Apply design operations atomically. Each is an object like {"op": "link", "component": "a.b",
        "relation": "uses", "target": "c"}; ops: add_component, add_need, add_criterion, remove_criterion,
        add_decision, set, link, unlink, move, remove."""
        parsed = [ops.from_json(o) for o in operations]
        return text(catalog.edit(ws(), parsed, EditMode.DRY_RUN if dry_run else EditMode.WRITE))

    def diff(base: str = "HEAD") -> str:
        return text(catalog.diff(ws(), Revision(base)))

    def review(base: str = "HEAD") -> str:
        return text(catalog.review(ws(), Revision(base)))

    def review_feedback(base: str = "HEAD") -> str:
        """Open change requests from the human review, item by item. Address each one."""
        return text(catalog.review_feedback(ws(), Revision(base)))

    def review_note(item: str, note: str, base: str = "HEAD") -> str:
        """Tell the reviewer something about one item: what you were unsure about, or where to look."""
        return text(catalog.review_note(ws(), catalog.review_items.ItemId(item), Text(note), Revision(base)))

    def review_record(base: str = "HEAD") -> str:
        return text(catalog.review_record(ws(), Revision(base)))

    def baseline() -> str:
        return text(catalog.baseline(ws()))

    def init(dry_run: bool = False) -> str:
        return text(catalog.init(catalog.new_project(project), EditMode.DRY_RUN if dry_run else EditMode.WRITE))

    return {Command.CHECK: check, Command.CONTEXT: context, Command.OUTLINE: outline, Command.MATRIX: matrix,
            Command.PLAN: plan, Command.NEXT: next_, Command.DIAGRAM: diagram, Command.EDIT: edit, Command.DIFF: diff,
            Command.BASELINE: baseline, Command.REVIEW: review, Command.REVIEW_FEEDBACK: review_feedback,
            Command.REVIEW_NOTE: review_note, Command.REVIEW_RECORD: review_record, Command.INIT: init}


def server(project: Path) -> MCPServer:
    srv = MCPServer("arch", instructions=INSTRUCTIONS)
    tools = _tools(project)
    for op in catalog.OPERATIONS:
        if op.audience is not catalog.Audience.ANYONE:
            continue  # verdicts are given by people, on the review page; an agent must not approve its own work
        fn = tools[op.command]
        description = op.summary + (f"\n\n{fn.__doc__}" if fn.__doc__ else "")
        srv.add_tool(fn, name=op.command.value, description=description, structured_output=False)
    return srv


def serve(project: Path) -> None:
    server(project).run("stdio")
