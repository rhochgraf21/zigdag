"""Every user-facing operation, defined once.

Realizes arch.integrate.catalog. Surfaces (the CLI, MCP, agent hooks) are thin layers over these
operations, so they cannot drift apart. Inputs are domain types (the surfaces parse text into them);
results are view objects that render themselves.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from arch import realize
from arch.change import Outcome as ApplyOutcome
from arch.change import apply
from arch.change.diff import diff as design_diff
from arch.change.ops import Operation as DesignOperation
from arch.check import Baseline
from arch.check import check as run_checks
from arch.guide.infer import infer
from arch.guide.next import ActionLimit, next_actions
from arch.guide.plan import plan as make_plan
from arch.model import codec
from arch.integrate import workspace
from arch.integrate.workspace import ProjectEdit, ProjectPath, Revision, Workspace

from arch.model.graph import Graph
from arch.model.ids import ComponentId, Text
from arch.model.matrix import matrix_of
from arch.view.context import DEFAULT_BUDGET_TOKENS, ContextTarget, TokenBudget, UnknownTarget
from arch.view.context import context as make_context
from arch.view.diagram import (
    DiagramFormat,
    DiagramView,
    Edges,
    MatrixView,
    ObservedMatrixView,
    changes,
    containment,
    observed_matrix,
    with_effects,
    with_observed,
)
from arch.view.outline import Depth
from arch.view.outline import outline as make_outline
from arch.view.report import (
    BaselineReport,
    DiffReport,
    EditMode,
    EditReport,
    FindingsReport,
    InfoFindings,
    InitReport,
    NextReport,
    PlanReport,
    Rendering,
)
from arch.view.render import Count
from arch.view.review import ReviewInput
from arch.view.review import review as make_review



class UnknownComponent(Exception):
    pass


UsageError = (UnknownComponent, UnknownTarget, workspace.NoRevision, workspace.StaleEdit, workspace.AlreadyDesigned)
NoProject = (workspace.NoProject, workspace.BadConfig)


class Outcome(enum.Enum):
    OK = 0
    BLOCKING = 1


@dataclass(frozen=True)
class Result:
    view: Rendering
    outcome: Outcome = Outcome.OK


class Access(enum.Enum):
    READS = "reads the design"
    WRITES = "writes the design"


class Command(enum.Enum):
    CHECK = "check"
    CONTEXT = "context"
    OUTLINE = "outline"
    MATRIX = "matrix"
    PLAN = "plan"
    EDIT = "edit"
    DIFF = "diff"
    BASELINE = "baseline"
    INIT = "init"
    NEXT = "next"
    DIAGRAM = "diagram"
    REVIEW = "review"


@dataclass(frozen=True)
class Operation:
    command: Command
    summary: Text
    access: Access
    run: Callable[..., Result]


def open_project(start: Path) -> Workspace:
    return workspace.find(start)


def new_project(start: Path) -> Workspace:
    return workspace.create(start)


def _graph(ws: Workspace) -> Graph:
    return Graph(ws.design())


def _component(g: Graph, cid: ComponentId | None) -> ComponentId | None:
    if cid is not None and cid not in g:
        raise UnknownComponent(f"no component '{cid}'")
    return cid


def check(ws: Workspace, info: InfoFindings = InfoFindings.COUNTED) -> Result:
    report = run_checks(_graph(ws), ws.facts(), ws.baseline(), ws.config().lexicon())
    return Result(FindingsReport(report, info), Outcome.BLOCKING if report.blocking else Outcome.OK)


def baseline(ws: Workspace) -> Result:
    """Accept today's errors as the starting point; fixed ones drop out."""
    old = ws.baseline()
    report = run_checks(_graph(ws), ws.facts())
    new = Baseline.of(report.findings)
    ws.write_baseline(new)
    return Result(BaselineReport(Count(len(old.entries)), Count(len(new.entries)), Count(len(old.stale(report)))))


def context(ws: Workspace, target: ContextTarget, budget: TokenBudget = DEFAULT_BUDGET_TOKENS) -> Result:
    g, facts = _graph(ws), ws.facts()
    return Result(make_context(g, facts, run_checks(g, facts, ws.baseline(), ws.config().lexicon()), target, budget))


def outline(ws: Workspace, root: ComponentId | None = None, depth: Depth | None = None) -> Result:
    g = _graph(ws)
    return Result(make_outline(g, _component(g, root), depth))


class MatrixOverlay(enum.Enum):
    DECLARED_ONLY = "declared"
    OBSERVED = "observed"  # also imports and co-change from git history


def matrix(ws: Workspace, parent: ComponentId | None = None, overlay: MatrixOverlay = MatrixOverlay.DECLARED_ONLY) -> Result:
    g = _graph(ws)
    parents = [c for c in ([_component(g, parent)] if parent else [c for c in g.ids() if g.children(c)]) if c is not None]
    if overlay is MatrixOverlay.OBSERVED:
        facts = ws.facts()
        return Result(ObservedMatrixView(tuple(observed_matrix(g, c, facts) for c in parents)))
    return Result(MatrixView(tuple(matrix_of(g, c) for c in parents)))


def next_(ws: Workspace, scope: ComponentId | None = None, limit: ActionLimit = ActionLimit(10)) -> Result:
    """The most valuable next actions, each naming the method or operation that applies."""
    g = _graph(ws)
    report = run_checks(g, ws.facts(), ws.baseline(), ws.config().lexicon())
    return Result(NextReport(next_actions(g, report, _component(g, scope), limit)))


class Overlay(enum.Enum):
    EFFECTS = "effects"  # colour components pure, effectful within constraints, or violating them
    OBSERVED = "observed"  # add undeclared imports and hidden coupling from git history


def diagram(ws: Workspace, root: ComponentId | None = None, depth: Depth = Depth(1), edges: Edges = Edges.REDUCED,
            overlays: frozenset[Overlay] = frozenset(), base: Revision | None = None,
            form: DiagramFormat = DiagramFormat.MARKDOWN) -> Result:
    """A containment diagram of `root`'s children, or (with `base`) only what changed since a revision."""
    g = _graph(ws)
    if base is not None:
        before = ws.design_at(base)
        return Result(DiagramView(changes(Graph(before), g, design_diff(before, ws.design())), form))
    d = containment(g, _component(g, root), depth, edges)
    if overlays:
        facts = ws.facts()
        if Overlay.EFFECTS in overlays:
            d = with_effects(d, g, facts, run_checks(g, facts, ws.baseline(), ws.config().lexicon()))
        if Overlay.OBSERVED in overlays:
            d = with_observed(d, g, facts)
    return Result(DiagramView(d, form))


def review(ws: Workspace, base: Revision = Revision("HEAD")) -> Result:
    """The change since `base` (from where the work diverged from it), layered for a reviewer."""
    since = ws.merge_base(base)
    before = ws.design_at(since)
    facts_before = realize.extract(ws.snapshot_at(since))
    after, facts_after = ws.design(), ws.facts()
    baseline, lexicon = ws.baseline(), ws.config().lexicon()
    inp = ReviewInput(
        base=Text(base), before=before, after=after, facts_before=facts_before, facts_after=facts_after,
        report_before=run_checks(Graph(before), facts_before, baseline, lexicon),
        report_after=run_checks(Graph(after), facts_after, baseline, lexicon),
        changed=ws.changed_files(since),
    )
    return Result(make_review(inp))


def plan(ws: Workspace, targets: Sequence[ComponentId] = ()) -> Result:
    g = _graph(ws)
    return Result(PlanReport(make_plan(g, [c for t in targets if (c := _component(g, t)) is not None])))


def edit(ws: Workspace, operations: Sequence[DesignOperation], mode: EditMode = EditMode.WRITE) -> Result:
    """Apply design operations atomically; with DRY_RUN, only report what would change."""
    snapshot = ws.snapshot()
    facts = realize.extract(snapshot)
    result = apply(ws.design(), operations, snapshot, facts.links)
    if result.outcome is ApplyOutcome.APPLIED and mode is EditMode.WRITE:
        ws.write(result.design_edits, result.source_edits)
    return Result(EditReport(result, mode), Outcome.OK if result.outcome is ApplyOutcome.APPLIED else Outcome.BLOCKING)


def init(ws: Workspace, mode: EditMode = EditMode.WRITE) -> Result:
    """Draft a design from the code, so an existing project starts with a design that passes."""
    snapshot = ws.snapshot()
    facts = realize.extract(snapshot)
    inference = infer(facts)
    result = apply(codec.load({}), inference.operations, snapshot, facts.links)
    edit_report = EditReport(result, mode)
    if result.outcome is not ApplyOutcome.APPLIED:
        return Result(InitReport(edit_report, Count(0), (), Count(0), inference.notes), Outcome.BLOCKING)
    remaining = Baseline.of(run_checks(Graph(result.after), facts).findings)
    if mode is EditMode.WRITE:
        ws.write(result.design_edits, result.source_edits)
        if remaining.entries:
            ws.write_baseline(remaining)
    cycles = tuple(tuple(Text(c) for c in group) for group in inference.cycles)
    return Result(InitReport(edit_report, Count(len(inference.components)), cycles, Count(len(remaining.entries)),
                             inference.notes))


def diff(ws: Workspace, base: Revision = Revision("HEAD")) -> Result:
    return Result(DiffReport(design_diff(ws.design_at(base), ws.design()), Text(base)))


OPERATIONS: tuple[Operation, ...] = (
    Operation(Command.CHECK, Text("Check the design, and the code against it"), Access.READS, check),
    Operation(Command.CONTEXT, Text("What you need to work on a component or file: intent, port, rules, neighbours"),
              Access.READS, context),
    Operation(Command.OUTLINE, Text("Show the decomposition as an outline, in realization order"), Access.READS, outline),
    Operation(Command.MATRIX, Text("Show design matrices (rows use columns)"), Access.READS, matrix),
    Operation(Command.NEXT, Text("The most valuable next actions, with the method or operation for each"),
              Access.READS, next_),
    Operation(Command.DIAGRAM, Text("Draw a component's parts and their uses (Mermaid or Graphviz), or what changed "
                                    "since a revision; overlays for effects and observed coupling"), Access.READS, diagram),
    Operation(Command.REVIEW, Text("Summarise a change for review: intent, design, structure, contracts, evidence, "
                                   "then code ranked by risk"), Access.READS, review),
    Operation(Command.PLAN, Text("Show realization layers, or the impact of changing components"), Access.READS, plan),
    Operation(Command.EDIT, Text("Change the design through validated operations (add, set, link, move, remove, ...)"),
              Access.WRITES, edit),
    Operation(Command.DIFF, Text("Show how the design changed since a git revision, by kind of change"), Access.READS, diff),
    Operation(Command.INIT, Text("Draft a design from existing code (draft components, uses = imports, cycles accepted)"),
              Access.WRITES, init),
    Operation(Command.BASELINE, Text("Accept current errors as the starting point, so only new ones block"),
              Access.WRITES, baseline),
)

__all__ = [o.run.__name__ for o in OPERATIONS] + [
    "Access", "Command", "ContextTarget", "Depth", "MatrixOverlay", "NoProject", "Operation", "Outcome", "Result", "Revision",
    "ActionLimit", "DiagramFormat", "Edges", "Overlay", "ProjectEdit", "ProjectPath", "TokenBudget", "UsageError", "Workspace", "new_project", "open_project",
]
