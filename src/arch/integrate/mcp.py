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
from arch.check.engine import FindingRef, Kind, Source, Station, Subject
from arch.check.critique import AnswerText
from arch.check.ledger import Answer
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
        set_criterion, add_decision, set, link, unlink, move, remove, split. To give a second function its own
        part, use split: {"op": "split", "component": "a.b", "labels": ["AC3"], "into": "a.b.c", "realizes": "...",
        "solution": "...", "hides": "..."}; it moves the criteria and re-links their tests."""
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

    def raise_(kind: str, subject: str, message: str, station: str, by: str, evidence: str | None = None,
               found_at: str | None = None, hint: str = "") -> str:
        """Record what you noticed while working, in your own work or in others': kind is defect, question or
        idea; station is where it was made (needs, requirements, solution, interface, code, evidence, review).
        Quote the exact words or line in evidence. An idea must say what it removes or unifies, and what it costs.
        Read `findings` for the subject first, and do not raise again what was declined without new evidence."""
        return text(catalog.raise_(ws(), Subject(subject), Kind(kind), Station(station), Text(message), Text(by),
                                   Source.AGENT, Text(evidence) if evidence else None,
                                   Station(found_at) if found_at else None, Text(hint)))

    def respond(answer: str, reason: str, refs: list[str], by: str, countermeasure: str | None = None) -> str:
        """Answer findings: fixed, accepted, declined or answered, with a reason. refs are RULE@SUBJECT#KEY as
        `findings` lists them. For an escape, also name the countermeasure."""
        return text(catalog.respond(ws(), Answer(answer), Text(reason), [FindingRef(r) for r in refs], Text(by),
                                    Text(countermeasure) if countermeasure else None))

    def critique(scope: str | None = None, mode: str = "list") -> str:
        """Which design text waits for a critic (mode "list"), the request to hand a critic ("request"), or a
        request about the rubric's own examples ("calibration"). Give a request to a reviewer that did not write
        the text and has no other context; record its JSON answer with critique_record."""
        return text(catalog.critique(ws(), ComponentId(scope) if scope else None, catalog.CritiqueMode(mode)))

    def critique_record(answer: str) -> str:
        """Record a critic's JSON answer. Only findings that quote the text exactly are kept."""
        return text(catalog.record_critique(ws(), AnswerText(answer)))

    def findings(listing: str = "open") -> str:
        """Findings and their answers: open, ideas, escapes or all."""
        return text(catalog.findings(ws(), catalog.Listing(listing)))

    return {Command.CHECK: check, Command.CONTEXT: context, Command.OUTLINE: outline, Command.MATRIX: matrix,
            Command.PLAN: plan, Command.NEXT: next_, Command.DIAGRAM: diagram, Command.EDIT: edit, Command.DIFF: diff,
            Command.BASELINE: baseline, Command.REVIEW: review, Command.REVIEW_FEEDBACK: review_feedback,
            Command.REVIEW_NOTE: review_note, Command.REVIEW_RECORD: review_record, Command.INIT: init,
            Command.RAISE: raise_, Command.RESPOND: respond, Command.FINDINGS: findings,
            Command.CRITIQUE: critique, Command.CRITIQUE_RECORD: critique_record}


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
