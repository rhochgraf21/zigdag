"""Every user-facing operation, defined once.

Realizes arch.integrate.catalog. Surfaces (the CLI, MCP, agent hooks) are thin layers over these
operations, so they cannot drift apart. Inputs are domain types (the surfaces parse text into them);
results are view objects that render themselves.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from arch import realize
from arch.change import Outcome as ApplyOutcome
from arch.change import ApplyResult, apply
from arch.change.diff import diff as design_diff
from arch.change.ops import Operation as DesignOperation
from arch.check import Ledger, Report
from arch.check import check as run_checks
from arch.check import critique as critic
from arch.check import promotion
from arch.check.engine import Finding, FindingKey, FindingRef, Kind, RuleId, Source, Station, Subject, parse_ref, ref_of
from arch.check.ledger import Answer, EntryName, Noticed, Response, accepting, digest_of, name_for, render_noticed, render_response
from arch.guide.infer import infer
from arch.guide.next import ActionLimit, next_actions
from arch.guide.plan import plan as make_plan
from arch.model import codec
from arch.integrate import workspace
from arch.integrate.workspace import ProjectEdit, ProjectPath, Revision, Workspace

from arch.model.graph import Graph
from arch.model.ids import ComponentId, Text, is_within
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
    CalibrationReport,
    CritiqueListing,
    CritiqueRecorded,
    CritiqueRequestView,
    InitReport,
    LedgerWrite,
    Listing,
    FindingsListing,
    NextReport,
    PlanReport,
    Rendering,
)
from arch.review import items as review_items
from arch.review.assess import ReviewInput
from arch.review.page import Board, ProjectRoot
from arch.review.session import Anchor, Category, Decision, Feedback, Record, Verdict, Weight
from arch.review.summary import review as make_review
from arch.view.render import Count



class UnknownComponent(Exception):
    pass


class LedgerRejected(Exception):
    """A finding or an answer that cannot be recorded as given."""


UsageError = (UnknownComponent, UnknownTarget, workspace.NoRevision, workspace.StaleEdit, workspace.AlreadyDesigned,
              LedgerRejected)
# ReviewRejected joins UsageError below, once defined
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
    RAISE = "raise"
    RESPOND = "respond"
    FINDINGS = "findings"
    CRITIQUE = "critique"
    CRITIQUE_RECORD = "critique_record"
    INIT = "init"
    NEXT = "next"
    DIAGRAM = "diagram"
    REVIEW = "review"
    REVIEW_BOARD = "review_board"
    REVIEW_DECIDE = "review_decide"
    REVIEW_FEEDBACK = "review_feedback"
    REVIEW_NOTE = "review_note"
    REVIEW_RECORD = "review_record"


class Audience(enum.Enum):
    ANYONE = "anyone"  # people and agents
    HUMAN_ONLY = "human only"  # never offered to agents: an author must not approve its own work


@dataclass(frozen=True)
class Operation:
    command: Command
    summary: Text
    access: Access
    run: Callable[..., Result]
    audience: Audience = Audience.ANYONE


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
    report = _report(ws)
    return Result(FindingsReport(report, info), Outcome.BLOCKING if report.blocking else Outcome.OK)


def _report(ws: Workspace, ledger: Ledger | None = None) -> Report:
    return run_checks(_graph(ws), ws.facts(), ws.ledger() if ledger is None else ledger, ws.config().lexicon())


_BASELINE = EntryName("baseline")
_BASELINE_REASON = Text("These errors existed when arch was adopted. Only new ones block; fix these over time.")


def baseline(ws: Workspace) -> Result:
    """Accept today's errors as the starting point, in one answer; fixed ones drop out of it."""
    ledger = ws.ledger()
    old = next((r for r in ledger.responses if r.name == _BASELINE), None)
    without = replace(ledger, responses=tuple(r for r in ledger.responses if r.name != _BASELINE))
    report = _report(ws, without)
    new = accepting(report.blocking, _BASELINE, Text("arch baseline"), _BASELINE_REASON)
    ws.write_ledger_entry(new.path, render_response(new))
    before = set(old.findings) if old else set()
    still = {f.identity for f in report.findings}
    return Result(BaselineReport(Count(len(before)), Count(len(new.findings)), Count(len(before - still))))


def raise_(ws: Workspace, subject: Subject, kind: Kind, station: Station, message: Text, by: Text,
           source: Source = Source.AGENT, evidence: Text | None = None, found_at: Station | None = None,
           hint: Text = Text("")) -> Result:
    """Record something noticed in the design, the code or the process: a defect, a question or an idea."""
    if source is Source.RULE:
        raise LedgerRejected("rules' findings are found again on every run; raise as a critic, a person or an agent")
    g = _graph(ws)
    name = _unique(name_for(f"{subject}-{message[:48]}"), {n.name for n in ws.ledger().noticed})
    finding = Finding(subject, RuleId(by), FindingKey(name), kind, message, hint, None, station, source=source,
                      evidence=evidence, found_at=found_at)
    noticed = Noticed(finding, name, digest_of(g, subject))
    ws.write_ledger_entry(noticed.path, render_noticed(noticed))
    return Result(LedgerWrite(Text(f"noted {kind.value} on {subject}: {ref_of(finding.identity)}"), noticed.path))


def respond(ws: Workspace, answer: Answer, reason: Text, refs: Sequence[FindingRef], by: Text,
            countermeasure: Text | None = None) -> Result:
    """Answer findings: fixed, accepted, declined or answered, always with a reason. Answered findings stop
    blocking; the answer itself is reviewed like any other change."""
    if not reason.strip():
        raise LedgerRejected("an answer needs a reason")
    try:
        identities = tuple(parse_ref(r) for r in refs)
    except ValueError as e:
        raise LedgerRejected(str(e)) from None
    known = {f.identity for f in _report(ws).findings}
    unknown = [ref_of(i) for i in identities if i not in known]
    if unknown:
        raise LedgerRejected(f"no such finding: {', '.join(unknown)} (see `arch findings`)")
    name = _unique(name_for(f"{answer.value}-{identities[0][1]}-{identities[0][2]}"), {r.name for r in ws.ledger().responses})
    response = Response(name, answer, by, reason, identities, countermeasure)
    ws.write_ledger_entry(response.path, render_response(response))
    return Result(LedgerWrite(Text(f"{answer.value} {len(identities)} finding{'s' * (len(identities) != 1)}"), response.path))


class CritiqueMode(enum.Enum):
    LIST = "list"  # which nodes wait for a critic
    REQUEST = "request"  # the request for a critic, as JSON
    CALIBRATION = "calibration"  # a request about the rubric's own examples, to measure a critic


def critique(ws: Workspace, scope: ComponentId | None = None, mode: CritiqueMode = CritiqueMode.LIST) -> Result:
    """The design text an independent critic must judge, or the request to hand that critic."""
    if mode is CritiqueMode.CALIBRATION:
        return Result(CritiqueRequestView(critic.calibration_request()))
    g = _graph(ws)
    _component(g, scope)
    report = run_checks(g, None, ws.ledger(), ws.config().lexicon())
    waiting = tuple(f.subject for f in report.findings if f.rule == "Q001" and not report.is_answered(f)
                    and (scope is None or (f.subject in g and is_within(ComponentId(f.subject), scope))))
    if mode is CritiqueMode.REQUEST:
        return Result(CritiqueRequestView(critic.request(g, waiting)))
    return Result(CritiqueListing(tuple(Text(w) for w in waiting)))


def record_critique(ws: Workspace, answer: critic.AnswerText) -> Result:
    """Accept what a critic can quote: its findings are stored, and each node it reviewed counts as critiqued
    until its text changes. A calibration answer is scored instead."""
    try:
        parsed = critic.CriticAnswer.parse(answer)
    except ValueError as e:
        raise LedgerRejected(str(e)) from None
    if parsed.purpose is critic.Purpose.CALIBRATION:
        return Result(CalibrationReport(parsed.critic, critic.score(parsed)))
    g, ledger = _graph(ws), ws.ledger()
    verdict = critic.judge(parsed, g)
    open_ = {(n.finding.subject, n.finding.rule, n.finding.evidence) for n in ledger.noticed
             if ledger.answer_for(n.finding.identity) is None}
    taken = {n.name for n in ledger.noticed}
    recorded = repeated = 0
    for f in verdict.findings:
        if (f.subject, f.rule, f.evidence) in open_:
            repeated += 1
            continue
        name = _unique(name_for(f"{f.subject}-{f.rule}"), taken)
        taken.add(name)
        noticed = Noticed(replace(f, key=FindingKey(name)), name, digest_of(g, f.subject))
        ws.write_ledger_entry(noticed.path, render_noticed(noticed))
        recorded += 1
    if verdict.reviewed:
        names = {r.name for r in ledger.responses}
        stamp = Response(_unique(name_for(f"critiqued-by-{parsed.critic}"), names), Answer.ANSWERED, parsed.critic,
                         Text(f"Judged by {parsed.critic} with rubric {critic.RUBRIC_VERSION}: "
                              f"{len(verdict.findings)} findings."),
                         tuple(critic.wanted(g, s) for s in verdict.reviewed))
        ws.write_ledger_entry(stamp.path, render_response(stamp))
    return Result(CritiqueRecorded(parsed.critic, Count(len(verdict.reviewed)), Count(recorded), Count(repeated),
                                   verdict.refused))


def _unique(base: EntryName, taken: set[EntryName]) -> EntryName:
    return next(EntryName(f"{base}-{i}" if i else base) for i in range(len(taken) + 1)
                if (f"{base}-{i}" if i else base) not in taken)


def findings(ws: Workspace, listing: Listing = Listing.OPEN) -> Result:
    """Findings with their answers: what is open, ideas waiting for an answer, escapes without a countermeasure."""
    return Result(FindingsListing(_report(ws), ws.ledger(), listing))


def context(ws: Workspace, target: ContextTarget, budget: TokenBudget = DEFAULT_BUDGET_TOKENS) -> Result:
    g, facts = _graph(ws), ws.facts()
    return Result(make_context(g, facts, run_checks(g, facts, ws.ledger(), ws.config().lexicon()), target, budget))


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
    report = run_checks(g, ws.facts(), ws.ledger(), ws.config().lexicon())
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
            d = with_effects(d, g, facts, run_checks(g, facts, ws.ledger(), ws.config().lexicon()))
        if Overlay.OBSERVED in overlays:
            d = with_observed(d, g, facts)
    return Result(DiagramView(d, form))


def _review_input(ws: Workspace, base: Revision) -> ReviewInput:
    since = ws.merge_base(base)
    before, snap_before = ws.design_at(since), ws.snapshot_at(since)
    after, snap_after = ws.design(), ws.snapshot()
    facts_before, facts_after = realize.extract(snap_before), realize.extract(snap_after)
    ledger, ledger_before, lexicon = ws.ledger(), ws.ledger_at(since), ws.config().lexicon()
    diffs = ws.diffs(since)
    report_before = run_checks(Graph(before), facts_before, ledger_before, lexicon)
    report_after = run_checks(Graph(after), facts_after, ledger, lexicon)
    # names are resolved only in the files a reviewer will read
    facts_before = replace(facts_before, references=realize.names(snap_before, [d.old_path or d.path for d in diffs]))
    facts_after = replace(facts_after, references=realize.names(snap_after, [d.path for d in diffs]))
    return ReviewInput(
        base=Text(base), design_before=before, design_after=after, facts_before=facts_before, facts_after=facts_after,
        report_before=report_before, report_after=report_after, changed=ws.changed_files(since), diffs=diffs,
        ledger_before=ledger_before, ledger_after=ledger,
    )


def review(ws: Workspace, base: Revision = Revision("HEAD")) -> Result:
    """The change since `base` (from where the work diverged from it), layered for a pull request."""
    return Result(make_review(_review_input(ws, base)))


def review_board(ws: Workspace, base: Revision = Revision("HEAD")) -> Result:
    """The change as review items, with the verdicts given so far: what the review page shows."""
    branch = ws.branch()
    inp = _review_input(ws, base)
    items = review_items.build(inp)
    glossary = review_items.Glossary.of(inp.design_after, items, Text(workspace.DESIGN_DIR))
    return Result(Board(items, ws.session(branch), Text(f"Review of {branch} against {base}"), glossary,
                        ProjectRoot(str(ws.root)), ws.config().editor))


class ReviewRejected(Exception):
    pass


@dataclass(frozen=True)
class VerdictInput:
    """A verdict as a reviewer gave it on the page."""

    item: review_items.ItemId
    digest: review_items.Digest  # what the reviewer was looking at
    decision: Decision
    comment: Text | None = None
    category: Category = Category.OTHER
    weight: Weight = Weight.BLOCKING
    anchor: Anchor | None = None


def review_decide(ws: Workspace, board: Board, verdict: VerdictInput) -> Result:
    """Record a reviewer's verdict on one item. People only: agents are never offered this."""
    item = next((i for i in board.items if i.id == verdict.item), None)
    if item is None:
        raise ReviewRejected(f"no review page '{verdict.item}'")
    if item.digest != verdict.digest:
        raise ReviewRejected("This page changed since you loaded it. Press Shift+R to load the current version.")
    session = ws.session(board.session.name).decide(Verdict(
        item.id, verdict.decision, item.digest, ws.reviewer(), verdict.comment, verdict.category, verdict.weight,
        verdict.anchor))
    ws.save_session(session)
    return Result(replace(board, session=session))


def review_feedback(ws: Workspace, base: Revision = Revision("HEAD")) -> Result:
    """Open change requests from the review, item by item: what the author (often an agent) must still do."""
    board = review_board(ws, base).view
    return Result(Feedback(board.session, board.items))


def review_note(ws: Workspace, item: review_items.ItemId, text: Text, base: Revision = Revision("HEAD")) -> Result:
    """The author's note on an item: what they were unsure about, or what the reviewer should look at."""
    board = review_board(ws, base).view
    if item not in {i.id for i in board.items}:
        raise ReviewRejected(f"no review item '{item}' (see `arch review --feedback --json` for ids)")
    session = ws.session(board.session.name).note(item, text)
    ws.save_session(session)
    return Result(replace(board, session=session))


def review_record(ws: Workspace, base: Revision = Revision("HEAD")) -> Result:
    """What the review concluded, for a commit message or pull-request description."""
    board = review_board(ws, base).view
    return Result(Record(board.session, board.items))


def plan(ws: Workspace, targets: Sequence[ComponentId] = ()) -> Result:
    g = _graph(ws)
    return Result(PlanReport(make_plan(g, [c for t in targets if (c := _component(g, t)) is not None])))


def edit(ws: Workspace, operations: Sequence[DesignOperation], mode: EditMode = EditMode.WRITE) -> Result:
    """Apply design operations atomically; with DRY_RUN, only report what would change."""
    snapshot = ws.snapshot()
    facts = realize.extract(snapshot)
    result = apply(ws.design(), operations, snapshot, facts.links)
    if result.outcome is ApplyOutcome.APPLIED:
        result = _promotion_gate(ws, result, facts)
    if result.outcome is ApplyOutcome.APPLIED and mode is EditMode.WRITE:
        ws.write(result.design_edits, result.source_edits)
    return Result(EditReport(result, mode), Outcome.OK if result.outcome is ApplyOutcome.APPLIED else Outcome.BLOCKING)


def _promotion_gate(ws: Workspace, result: ApplyResult, facts) -> ApplyResult:
    """A status may rise only when nothing is open at the stations it claims: the definition of done."""
    before, after = Graph(result.before), Graph(result.after)
    if all(c not in before or before[c].status == after[c].status for c in after.ids()):
        return result
    open_ = promotion.blockers(before, after, run_checks(after, facts, ws.ledger(), ws.config().lexicon()))
    if not open_:
        return result
    first = open_[0]
    reason = (f"{len(open_)} open finding{'s' * (len(open_) != 1)} at the stations this status claims, first "
              f"{ref_of(first.identity)}: {first.message}. Fix or answer them (`arch respond`), then raise the status")
    return replace(result, outcome=ApplyOutcome.REJECTED, after=result.before, design_edits=(), source_edits=(),
                   new_findings=open_, reason=Text(reason))


def init(ws: Workspace, mode: EditMode = EditMode.WRITE) -> Result:
    """Draft a design from the code, so an existing project starts with a design that passes."""
    snapshot = ws.snapshot()
    facts = realize.extract(snapshot)
    inference = infer(facts)
    result = apply(codec.load({}), inference.operations, snapshot, facts.links)
    edit_report = EditReport(result, mode)
    if result.outcome is not ApplyOutcome.APPLIED:
        return Result(InitReport(edit_report, Count(0), (), Count(0), inference.notes), Outcome.BLOCKING)
    remaining = accepting(run_checks(Graph(result.after), facts).blocking, _BASELINE, Text("arch init"), _BASELINE_REASON)
    if mode is EditMode.WRITE:
        ws.write(result.design_edits, result.source_edits)
        if remaining.findings:
            ws.write_ledger_entry(remaining.path, render_response(remaining))
    cycles = tuple(tuple(Text(c) for c in group) for group in inference.cycles)
    return Result(InitReport(edit_report, Count(len(inference.components)), cycles, Count(len(remaining.findings)),
                             inference.notes))


def diff(ws: Workspace, base: Revision = Revision("HEAD")) -> Result:
    return Result(DiffReport(design_diff(ws.design_at(base), ws.design()), Text(base)))


UsageError = (*UsageError, ReviewRejected)


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
    Operation(Command.REVIEW_BOARD, Text("The change as review items with the verdicts so far"), Access.READS, review_board,
              Audience.HUMAN_ONLY),
    Operation(Command.REVIEW_DECIDE, Text("Record a reviewer's verdict on one item"), Access.WRITES, review_decide,
              Audience.HUMAN_ONLY),
    Operation(Command.REVIEW_FEEDBACK, Text("Open change requests from the review, item by item"), Access.READS,
              review_feedback),
    Operation(Command.REVIEW_NOTE, Text("Add the author's note to a review item"), Access.WRITES, review_note),
    Operation(Command.REVIEW_RECORD, Text("What the review concluded, for a commit message or PR description"),
              Access.READS, review_record),
    Operation(Command.PLAN, Text("Show realization layers, or the impact of changing components"), Access.READS, plan),
    Operation(Command.EDIT, Text("Change the design through validated operations (add, set, link, move, remove, ...)"),
              Access.WRITES, edit),
    Operation(Command.DIFF, Text("Show how the design changed since a git revision, by kind of change"), Access.READS, diff),
    Operation(Command.INIT, Text("Draft a design from existing code (draft components, uses = imports, cycles accepted)"),
              Access.WRITES, init),
    Operation(Command.BASELINE, Text("Accept current errors as the starting point, so only new ones block"),
              Access.WRITES, baseline),
    Operation(Command.RAISE, Text("Record something you noticed: a defect, a question or an idea, about the design, "
                                  "the code or the process"), Access.WRITES, raise_),
    Operation(Command.RESPOND, Text("Answer findings: fixed, accepted, declined or answered, always with a reason"),
              Access.WRITES, respond),
    Operation(Command.FINDINGS, Text("List findings and their answers: open ones, ideas waiting for an answer, escapes "
                                     "without a countermeasure, and how often each source's findings are accepted"),
              Access.READS, findings),
    Operation(Command.CRITIQUE, Text("Which design text waits for an independent critic, and the request to hand it "
                                     "(or a calibration request about the rubric's own examples)"), Access.READS, critique),
    Operation(Command.CRITIQUE_RECORD, Text("Record a critic's answer: findings it can quote are stored, and the nodes it "
                                            "reviewed count as critiqued until their text changes"),
              Access.WRITES, record_critique),
)

__all__ = [o.run.__name__ for o in OPERATIONS] + [
    "Access", "Command", "ContextTarget", "Depth", "MatrixOverlay", "NoProject", "Operation", "Outcome", "Result", "Revision",
    "ActionLimit", "Audience", "CritiqueMode", "DiagramFormat", "LedgerRejected", "Listing", "ReviewRejected", "VerdictInput", "Edges", "Overlay", "ProjectEdit", "ProjectPath", "TokenBudget", "UsageError", "Workspace", "new_project", "open_project",
]
