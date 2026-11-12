"""The work of a change, part by part (DESIGN2 §4.8): what the change asks of each part of the design and has not
been given yet, and from that, what can be built or landed now.

Nothing here is kept between runs. What a change asks is worked out each time from the project where the change
began and the project as it is, so it cannot go out of date when the design is amended while parts are being built.
"""

from __future__ import annotations

import enum
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

import deal

from zigdag.core.checks.directions import standings
from zigdag.core.checks.evidence import EVIDENCE, unanswered
from zigdag.core.checks.run import Analysis
from zigdag.core.code import Outcome, Test, TestId
from zigdag.core.findings import Finding, Result, Subject
from zigdag.core.kinds.registry import Direction
from zigdag.core.log import Kind, ThreadId
from zigdag.core.names import FrName, Revision, is_within, named_fr
from zigdag.core.record.entries import PHYSICAL_PREFIX
from zigdag.core.resolve import COVERAGE
from zigdag.core.review import Change, diff, new_findings
from zigdag.core.texts import Say, Written

_STANDS_IN_THE_WAY = (Result.BREAKS, Result.QUESTION)  # what a change may not leave behind, whatever the tests show


@dataclass(frozen=True)
class Asked:
    """What a change asks of one part and has not been given yet."""

    part: FrName
    # Each thing asked: a test of a statement the change added or changed, first, since the rest follows from
    # building what the statements say; then what the change broke or left unsure in the part, and the code a part
    # has not got.
    findings: tuple[Finding, ...]

    @property
    @deal.ensure(lambda self, result: len(result) == len(self.findings))
    def reasons(self) -> tuple[Say, ...]:
        """Each thing asked, in a line."""
        return tuple(Say(f"{f.about}: {f.say}") for f in self.findings)


@deal.ensure(lambda a, result: len(result) == len(a.record.frs) and set(result) == set(a.record.frs))  # each once
def build_order(a: Analysis) -> list[FrName]:
    """Every DP, after the siblings it depends on: the order the design matrix allows building in."""
    if a.tree is None or a.relations is None:
        return sorted(a.record.frs)
    tree, relations = a.tree, a.relations
    out: list[FrName] = []

    def visit(name: FrName) -> None:
        out.append(name)
        order, cells = relations.matrix(tree, name)
        placed: list[FrName] = []
        remaining = list(order)
        while remaining:
            ready = [c for c in remaining if all((c, d) not in cells for d in remaining if d != c)] or remaining[:1]
            for c in ready:
                remaining.remove(c)
                placed.append(c)
        for c in placed:
            visit(c)

    if a.record.root is not None:
        visit(a.record.root.name)
    return out + sorted(set(a.record.frs) - set(out))


def _of_the_design(a: Analysis) -> frozenset[Finding]:
    """The findings about the design itself, such as a statement outside its grammar: no part's code answers them."""
    return frozenset(f for s in standings(a, a.report) if s.direction is Direction.DESIGN for f in s.findings)


def _brought(before: Analysis, after: Analysis) -> list[Finding]:
    """The breaks and questions a change brought, and the parts it left without code. A rule the project could not
    be checked by where the change began had no chance to find anything there, so what it finds now is not new."""
    return [f for f in new_findings(before.report, after.report)
            if f.rule not in before.unchecked and (f.result in _STANDS_IN_THE_WAY or f.rule == COVERAGE)]


@deal.ensure(lambda before, after, result: all(f in after.report.findings for f in result))
def unsettled(before: Analysis, after: Analysis) -> tuple[Finding, ...]:
    """What a change brought that is wrong with the design itself. Until it is put right the design is not settled,
    and nothing is built against it."""
    design = _of_the_design(after)
    return tuple(f for f in _brought(before, after) if f in design and f.rule != COVERAGE)


def _part_of(a: Analysis, f: Finding) -> FrName | None:
    """The part a finding is work for: the one it is about, or the root for one about no part, such as a setting."""
    return a.dp_of_finding(f) or (a.record.root.name if a.record.root is not None else None)


@deal.ensure(lambda before, after, result: all(name == a.part and a.findings for name, a in result.items()))
@deal.ensure(lambda before, after, result: list(result) == sorted(result))
def asked(before: Analysis, after: Analysis) -> Mapping[FrName, Asked]:
    """What a change asks of each part and has not been given yet, by part. `before` is the project where the change
    began, and `after` the project as it is.

    A part is asked for a test of each statement the change added or changed, for code when it has none, and for
    every break and question the change brought to its code. What is wrong with the design itself is no part's to
    answer (see unsettled). Things to do that only running the tests answers are left out: this must say the same of
    a revision read from git, whose tests never ran, as of a folder where they did.
    """
    design = _of_the_design(after)
    found = [*unanswered(before.record, before.tests, after.record, after.tests),
             *(f for f in _brought(before, after) if f not in design or f.rule == COVERAGE)]
    findings: dict[FrName, list[Finding]] = {}
    for f in found:
        part = _part_of(after, f)
        if part is not None:
            findings.setdefault(part, []).append(f)
    return {part: Asked(part, tuple(findings[part])) for part in sorted(findings)}


@dataclass(frozen=True)
class Waiting:
    """The failing tests of a part's branch, told apart: those that ran the code of a part the change has not been
    given yet, and so wait for it to land, and those that are the branch's own to fix."""

    on: tuple[FrName, ...]  # the parts waited for
    tests: tuple[Test, ...]  # the failing tests that wait for them
    own: tuple[Test, ...]  # the failing tests that wait for nothing
    set_aside: tuple[Finding, ...]  # the breaks that say only that a waiting test failed

    @property
    @deal.ensure(lambda self, result: result == (bool(self.tests) and not self.own))
    def is_all(self) -> bool:
        """Whether every test that fails does so for want of another part: nothing is left for this branch to fix."""
        return bool(self.tests) and not self.own


NOT_WAITING = Waiting((), (), (), ())
_FAILED = (Outcome.FAILED, Outcome.ERROR)


def _apart(part: FrName, other: FrName) -> bool:
    """Whether neither part is inside the other, so that each can be built without the other's code."""
    return not is_within(part, other) and not is_within(other, part)


@deal.ensure(lambda after, part, unbuilt, result: all(_apart(part, other) and other in unbuilt for other in result.on))
@deal.ensure(lambda after, part, unbuilt, result: all(f in after.report.findings and f.result is Result.BREAKS
                                                      for f in result.set_aside))
def waiting(after: Analysis, part: FrName, unbuilt: Collection[FrName]) -> Waiting:
    """Which failing tests of a part's branch wait for other parts. A test waits when, as the watcher saw it run, it
    ran code of a part the change still asks something of: that code is not written yet, so what the test shows of
    this part cannot be told until it is. `unbuilt` is every part the change still asks something of."""
    code, tree = after.code, after.tree
    if code is None or tree is None or code.observed is None:
        return NOT_WAITING
    others = sorted(other for other in unbuilt if _apart(part, other))
    waits: dict[TestId, set[FrName]] = {}
    own = []
    for test in code.tests:
        if code.results.get(test.id) not in _FAILED:
            continue
        run = code.observed.run_of(test.id)
        ran = {owner for unit in (run.ran if run is not None else ()) if (owner := tree.owner(unit)) is not None}
        needed = {other for other in others if any(is_within(owner, other) for owner in ran)}
        if needed:
            waits[test.id] = needed
        else:
            own.append(test)
    held_up = tuple(t for t in code.tests if t.id in waits)
    said_of = {(link.target, t.span) for t in held_up for link in t.links}
    set_aside = tuple(f for f in after.report.findings if f.result is Result.BREAKS and f.rule == EVIDENCE
                      and (f.about, f.span) in said_of)
    return Waiting(tuple(sorted({other for needed in waits.values() for other in needed})), held_up, tuple(own),
                   set_aside)


# ---- what to do next ---------------------------------------------------------------------------------------------

def _uses(a: Analysis, part: FrName) -> frozenset[FrName]:
    """The parts whose code a part's code uses."""
    if a.relations is None:
        return frozenset()
    return frozenset(edge.target for edge in a.relations.edges if is_within(edge.source, part))


@deal.ensure(lambda a, part, about, result: result or _apart(part, about))  # a part is concerned with itself
def concerns(a: Analysis, part: FrName, about: FrName) -> bool:
    """Whether what is said of one part concerns another: when it is said of the part itself, of a part it is inside,
    whose rules cover it, of a part inside it, or of a part whose code it uses."""
    return not _apart(part, about) or any(not _apart(used, about) for used in _uses(a, part))


@deal.ensure(lambda a, on, result: result is None or result in a.record.frs)
def part_named(a: Analysis, on: Subject) -> FrName | None:
    """The part a name in the log is about: an FR, a statement's FR, or a physical entry's; None for a name that is
    about no one part, such as a job or a rule."""
    name = named_fr(Written(on.removeprefix(PHYSICAL_PREFIX)))
    return FrName(name) if name in a.record.frs else None


class Step(enum.Enum):
    """What there is to do next on a change that is built part by part."""

    BUILD = "build"  # a part is free: one agent builds it, on its branch
    LAND = "land"  # a part is built: one agent brings its branch up to date and merges it
    WAIT = "wait"  # everything left is someone's already, or waits for it: ask again when an agent finishes
    BLOCKED = "blocked"  # waiting will not help: a person has to settle something first
    DONE = "done"  # the change asks nothing more


@dataclass(frozen=True)
class Taken:
    """A part someone has: its branch exists."""

    part: FrName
    folder: Analysis | None  # the project in the folder its branch is checked out in; None while it is in none


@dataclass(frozen=True)
class Answer:
    """What to do next, with the part it is about and each reason, a line each."""

    step: Step
    part: FrName | None = None  # the part to build or land
    why: tuple[Say, ...] = ()


class _Standing(enum.Enum):
    """How a taken part stands, as far as its folder shows."""

    BEING_BUILT = "being built"
    BEHIND = "behind the design"  # the design changed where it lands, in a way that concerns it
    BUILT = "built"
    WAITS = "built, and waits"


def _left(before: Analysis, folder: Analysis, part: FrName) -> tuple[bool, Waiting]:
    """Whether a part's folder still shows work of its own, and what its failing tests wait for."""
    still = asked(before, folder)
    waits = waiting(folder, part, still)
    mine = still.get(part)
    own = mine is not None and any(f not in waits.set_aside for f in mine.findings)
    return own or bool(waits.own), waits


def _amended(line: Analysis, folder: Analysis, part: FrName) -> bool:
    """Whether the design where a part lands says something of the part, or of what it uses, that the part's folder
    does not have: the part is being built against a design that has moved on."""
    here, there = folder.entries, line.entries
    differing = {name for name in {*here, *there}
                 if (name not in here or name not in there or here[name].digest != there[name].digest)}
    scopes = {(there.get(name) or here[name]).scope for name in differing}
    return any(scope is not None and scope in line.record.frs and concerns(line, part, FrName(scope))
               for scope in scopes)


def _standing(before: Analysis, line: Analysis, taken: Taken, unbuilt: Collection[FrName]) -> tuple[_Standing,
                                                                                                  tuple[FrName, ...]]:
    """How a taken part stands, and the parts it waits for. A folder whose tests never ran shows nothing of whether
    the part works, so the part is still being built. A part that waits only for parts that have landed since waits
    for nothing: it is ready to land, where its branch is brought up to date and its tests run again."""
    folder = taken.folder
    if folder is None or folder.code is None or not folder.code.reports_read:
        return _Standing.BEING_BUILT, ()
    if _amended(line, folder, taken.part):
        return _Standing.BEHIND, ()
    unfinished, waits = _left(before, folder, taken.part)
    if unfinished:
        return _Standing.BEING_BUILT, ()
    still = tuple(other for other in waits.on if other in unbuilt)
    return (_Standing.WAITS, still) if still else (_Standing.BUILT, ())


@dataclass(frozen=True)
class Stop:
    """Something raised since the change began that nobody has answered: the parts it concerns stop for it."""

    id: ThreadId  # what it is answered by
    kind: Kind
    on: Subject  # what it was raised on
    say: Say
    raised_from: FrName | None  # the part whose folder it was raised in; None when it was raised where parts land
    stopped: tuple[FrName, ...]  # the taken parts it concerns
    going_on: tuple[FrName, ...]  # the taken parts it does not

    @property
    @deal.ensure(lambda self, result: len(result) >= 2 and result[0].startswith(self.kind.value))
    def said(self) -> tuple[Say, ...]:
        where = self.raised_from or "where the parts land"
        return (Say(f"{self.kind.value} on {self.on}, raised from {where}: {self.say}"),
                *((Say(f"stopped: {', '.join(self.stopped)}"),) if self.stopped else ()),
                *((Say(f"continuing: {', '.join(self.going_on)}"),) if self.going_on else ()),
                Say(f"when it is settled: zigdag answer {self.id} <answer> <why> --by <who>"
                    + (f", in the folder of {self.raised_from}" if self.raised_from else "")))


_STOPS = (Kind.QUESTION, Kind.DEFECT)  # an idea can wait; a question or a defect says what is being built may be wrong


@deal.ensure(lambda before, line, taken, result: all(set(s.stopped).isdisjoint(s.going_on) for s in result))
def stops(before: Analysis, line: Analysis, taken: Sequence[Taken]) -> tuple[Stop, ...]:
    """Each question and defect raised since the change began that is answered nowhere: where the parts land, or in
    any part's folder, since a part's log is not seen elsewhere until the part lands."""
    logs: list[tuple[FrName | None, Analysis]] = [(None, line), *((t.part, t.folder) for t in taken
                                                                   if t.folder is not None)]
    known = {thread.raised.id for thread in before.log.threads}
    answered = {thread.raised.id for _, a in logs for thread in a.log.threads if not thread.open}
    out: dict[ThreadId, Stop] = {}
    for raised_from, a in logs:
        for thread in a.log.threads:
            raised = thread.raised
            if raised.id in known | answered | set(out) or raised.kind not in _STOPS:
                continue
            about = part_named(line, Subject(raised.on))
            stopped = tuple(t.part for t in taken if t.part == raised_from or (
                about is not None and concerns(t.folder or line, t.part, about)))
            out[raised.id] = Stop(raised.id, raised.kind, Subject(raised.on), Say(raised.say), raised_from, stopped,
                                  tuple(t.part for t in taken if t.part not in stopped))
    return tuple(out.values())


def _counted(n: int) -> str:
    return "1 part" if n == 1 else f"{n} parts"


@deal.ensure(lambda before, line, taken, unsettled_, result: (result.part is not None) == (
    result.step in (Step.BUILD, Step.LAND)))
@deal.ensure(lambda before, line, taken, unsettled_, result: result.step is not Step.BLOCKED or bool(result.why))
@deal.ensure(lambda before, line, taken, unsettled_, result: not unsettled_ or result.step is Step.BLOCKED)
def next_step(before: Analysis, line: Analysis, taken: Sequence[Taken], unsettled_: Sequence[Say]) -> Answer:
    """What to do next on a change. `before` is the project where the change began, `line` the project where its
    parts land, `taken` the parts whose branches exist, and `unsettled_` each reason the design is not settled yet.

    The order is the order to deal with things in. While the design is not settled, or a question about it is open,
    nothing new is handed out: what is built against a design that is about to move may be built for nothing. Then a
    part that is built lands, since that is what other parts wait for. Then a part is built: one whose branch fell
    behind the design first, then the first free one in the order the design matrix allows. A part is not handed
    out while the change still asks something of a part inside it, which is built first, or while someone has a
    part it is inside or holds: two agents in one part's code is what the branches are there to prevent."""
    if unsettled_:
        return Answer(Step.BLOCKED, None, (Say("the design is not settled:"), *unsettled_))
    unbuilt = asked(before, line)
    # A branch left over from a part that has landed is nobody's work: only a part still asked of is taken.
    mine = {t.part: t for t in taken if t.part in unbuilt}
    raised = stops(before, line, tuple(mine.values()))
    if raised:
        return Answer(Step.BLOCKED, None, tuple(said for stop in raised for said in stop.said))
    if not unbuilt:
        return Answer(Step.DONE)
    order = {name: at for at, name in enumerate(build_order(line))}
    in_order = sorted(unbuilt, key=lambda part: order.get(part, len(order)))
    standing = {part: _standing(before, line, t, unbuilt) for part, t in mine.items()}
    for part in in_order:
        if part in standing and standing[part][0] is _Standing.BUILT:
            return Answer(Step.LAND, part)
    for part in in_order:
        if part in standing and standing[part][0] is _Standing.BEHIND:
            return Answer(Step.BUILD, part, (Say("the design changed where it lands since its branch last had it: "
                                                 "bring the branch up to date first"),))
    waits: list[Say] = []
    for part in in_order:
        if part in mine:
            continue
        inside = sorted(other for other in unbuilt if other != part and is_within(other, part))
        around = sorted(other for other in mine if not _apart(part, other))
        if not inside and not around:
            return Answer(Step.BUILD, part)
        waits.append(Say(f"{part} waits for {', '.join(inside)}, inside it") if inside else
                     Say(f"{part} waits for {', '.join(around)}, which is being built around it"))
    being_built = [part for part, (how, _) in standing.items() if how is _Standing.BEING_BUILT]
    held_up = [Say(f"{part} is built, and needs {', '.join(needs)} to land")
               for part, (how, needs) in standing.items() if how is _Standing.WAITS]
    return Answer(Step.WAIT, None, (*((Say(f"{_counted(len(being_built))} being built: "
                                           f"{', '.join(sorted(being_built))}"),) if being_built else ()),
                                    *held_up, *waits))


# ---- what a change says of one part ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Delta:
    """What a change says of one part, for whoever builds it."""

    base: Revision  # where the change began
    changes: tuple[Change, ...]  # the entries of the design that concern the part, as the change changed them
    asked: Asked | None  # what the change asks of the part and has not been given yet; None when it asks nothing


@deal.ensure(lambda base, before, after, part, result: result.base == base and (
    result.asked is None or result.asked.part == part))
def delta(base: Revision, before: Analysis, after: Analysis, part: FrName) -> Delta:
    """What a change says of one part: each entry it changed that is about the part, a part around or inside it, or a
    part whose code it uses; and what it asks of the part. An entry about no part, such as a job, is left out."""
    changed = diff(before.record, after.record, before.sentences, after.sentences)
    mine = tuple(c for c in changed if (scope := c.entry.scope) is not None and scope in after.record.frs
                 and concerns(after, part, FrName(scope)))
    return Delta(base, mine, asked(before, after).get(part))
