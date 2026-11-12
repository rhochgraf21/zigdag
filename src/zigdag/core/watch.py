"""What a test watcher watches (DESIGN2 §4.5), worked out from an analysis: whose each unit of code is, which
structures only their owner may change, which operations are called again to check they depend only on their
arguments, which values' text must not be written out, which contracts are run on generated inputs, and which
functions with contracts are mutated to see whether their contracts notice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import deal

from zigdag.core import codec
from zigdag.core.checks.data_rules import protected_types
from zigdag.core.checks.run import Analysis
from zigdag.core.kinds.registry import DATA_FLOW, EFFECTS, MUTATION, Part
from zigdag.core.settings import CARRIED_FILE, OBSERVED_FILE
from zigdag.core.code import CodeModel, Mutant, Place, Qualified, SearchBound, SymbolKind, TestId
from zigdag.core.findings import Digest, RecordPath, digest_of
from zigdag.core.names import CodePath, FrName
from zigdag.core.measures import Count, Seconds
from zigdag.core.texts import Content, FileText

PLAN_VARIABLE = "ZIGDAG_WATCH"  # the environment variable that gives the watcher the plan's path


@dataclass(frozen=True)
class Guarded:
    """A recorded structure, and the component whose code alone may change it."""

    type: Qualified
    owner: FrName


@dataclass(frozen=True)
class Mutated:
    """A pure function with a contract whose mutants are made, and how far to search for an input that one of them
    behaves differently on (DESIGN2 §4.5). Only pure functions are mutated: a mutant is run, so a mutant of code with
    effects could do anything that code can, such as delete the wrong file. A function counts as pure only when its
    code declares so and nothing zigdag reads in it, or in what it calls, says otherwise."""

    place: Place
    paths: Count  # at most this many paths through the code are explored
    seconds: Seconds  # and for at most this long
    callees: Digest = digest_of()  # the source of every project function it calls, however indirectly

    @property
    @deal.ensure(lambda self, result: (result.paths, result.seconds) == (self.paths, self.seconds))
    def bound(self) -> SearchBound:
        return SearchBound(self.paths, self.seconds)


@dataclass(frozen=True)
class LastRun:
    """The mutants earlier watched runs made, to carry over from (DESIGN2 §4.5). Each mutant says what its fate
    depended on, so mutants from runs of different ages can be kept side by side: whether one still stands is
    decided by its own digests, never by when it was made."""

    mutants: tuple[Mutant, ...] = ()

    @deal.ensure(lambda self, place, result: all(m.at == place and m in self.mutants for m in result))
    def of(self, place: Place) -> tuple[Mutant, ...]:
        """The mutants an earlier run made of one function."""
        return tuple(m for m in self.mutants if m.at == place)

    @deal.ensure(lambda self, newer, result: {m.at for m in result.mutants} == {
        m.at for m in (*self.mutants, *newer.mutants)})
    @deal.ensure(lambda self, newer, result: all(result.of(p) == newer.of(p) for p in {m.at for m in newer.mutants}))
    def merged(self, newer: LastRun) -> LastRun:
        """These mutants, with each function that the newer ones are about taken from the newer ones instead."""
        replaced = {m.at for m in newer.mutants}
        return LastRun((*(m for m in self.mutants if m.at not in replaced), *newer.mutants))

    @deal.ensure(lambda self, place, made, result: result.of(place) == tuple(made))
    def with_function(self, place: Place, made: Iterable[Mutant]) -> LastRun:
        """These mutants, with one function's replaced by the ones just made of it."""
        return LastRun((*(m for m in self.mutants if m.at != place), *made))

    @deal.ensure(lambda self, places, result: {m.at for m in result.mutants} <= set(places))
    def within(self, places: Iterable[Place]) -> LastRun:
        """Only the mutants of functions that still have contracts, so what is carried does not grow forever."""
        kept = frozenset(places)
        return LastRun(tuple(m for m in self.mutants if m.at in kept))

    def to_text(self) -> FileText:
        return codec.dumps(self)

    @staticmethod
    @deal.post(lambda result: isinstance(result, LastRun | codec.Unreadable))
    def from_text(text: FileText) -> LastRun | codec.Unreadable:
        return codec.loads(LastRun, text)


@dataclass(frozen=True)
class WatchPlan:
    sources: Mapping[RecordPath, CodePath]  # each source file, and the unit it is
    tests: tuple[RecordPath, ...]  # each test file
    owners: Mapping[CodePath, FrName]  # each unit, and the DP whose code it is
    guarded: tuple[Guarded, ...]
    replayed: tuple[Place, ...]  # operations under a rule that allows no effects
    protected: tuple[Qualified, ...]  # types whose values' text is watched for in what the code writes
    contracts: tuple[Place, ...]  # operations with contracts, run on generated inputs
    mutated: tuple[Mutated, ...] = ()  # operations with contracts whose mutants are judged
    observed: RecordPath = OBSERVED_FILE
    last_run: LastRun = field(default_factory=LastRun)  # what earlier runs made, to carry mutants over from
    carried: RecordPath = CARRIED_FILE  # where the watcher keeps the mutants judged so far, as it goes

    @deal.ensure(lambda self, result: WatchPlan.from_text(result) == self)  # the watcher reads the plan as made
    def to_text(self) -> FileText:
        return codec.dumps(self)

    @staticmethod
    @deal.post(lambda result: isinstance(result, WatchPlan | codec.Unreadable))
    def from_text(text: FileText) -> WatchPlan | codec.Unreadable:
        return codec.loads(WatchPlan, text)


def _unknowable(model: CodeModel) -> frozenset[Place]:
    """The places that do something that cannot be read, or call code that does, however indirectly."""
    found = {u.at for u in model.unknowns}
    callers: dict[Place, set[Place]] = {}
    for c in model.calls:
        callee = model.symbols.get(c.callee)
        if callee is not None:
            callers.setdefault(callee.place, set()).add(c.caller)
    work = list(found)
    while work:
        for caller in callers.get(work.pop(), ()):
            if caller not in found:
                found.add(caller)
                work.append(caller)
    return frozenset(found)


def _pure(effects: Mapping[Place, Mapping], unknowable: frozenset[Place], place: Place) -> bool:
    """Whether a function has no effect, directly or through what it calls, and does nothing that cannot be read."""
    return not effects.get(place) and place not in unknowable


def _sorted(places: Iterable[Place]) -> tuple[Place, ...]:
    return tuple(sorted(set(places), key=str))


def _source(model: CodeModel, name: Qualified, sources: Mapping[RecordPath, FileText]) -> Content:
    """A symbol's source, as its span and size place it in the file it was read from."""
    symbol = model.symbols[name]
    lines = (sources.get(symbol.span.path) or "").splitlines()
    return Content("\n".join(lines[symbol.span.line - 1:symbol.span.line - 1 + symbol.size]))


@deal.ensure(lambda model, sources, result: set(result) <= {s.place for s in model.symbols.values()})
def _callees(model: CodeModel, sources: Mapping[RecordPath, FileText]) -> Mapping[Place, Digest]:
    """For each function, a digest of the source of every project function it calls, however indirectly, as the
    calls zigdag read or saw show them. A mutant's fate can change when any of them does, since its contract cases
    run through them."""
    calls: dict[Place, set[Qualified]] = {}
    for c in model.calls:
        if c.callee in model.symbols:
            calls.setdefault(c.caller, set()).add(c.callee)
    out = {}
    for symbol in model.symbols.values():
        reached: set[Qualified] = set()
        work = list(calls.get(symbol.place, ()))
        while work:
            name = work.pop()
            if name not in reached and name != symbol.qualified:
                reached.add(name)
                work += calls.get(model.symbols[name].place, ())
        out[symbol.place] = digest_of(*(Content(f"{n}\n{_source(model, n, sources)}") for n in sorted(reached)))
    return out


@deal.ensure(lambda analysis, tests, sources, result: (result is None) == (analysis.context is None))
@deal.ensure(lambda analysis, tests, sources, result: result is None or {m.place for m in result.mutated} <= set(
    result.contracts))  # only a function with a contract is mutated
def plan(analysis: Analysis, tests: Iterable[RecordPath], sources: Mapping[RecordPath, FileText]) -> WatchPlan | None:
    """The plan for watching a project's tests, given the source it was read from; None when the code was not
    read."""
    ctx = analysis.context
    if ctx is None:
        return None
    model, tree = ctx.model, ctx.tree
    operations = [s for s in model.symbols.values() if s.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD)]
    replayed: list[Place] = []
    mutated: list[Mutated] = []
    unknowable = _unknowable(model)
    protected: set[Qualified] = set()
    callees = _callees(model, sources)
    for rule in analysis.rules:
        covered = [s.place for s in operations
                   if ctx.in_scope(rule, tree.owner(s.qualified)) and not rule.skips(tree, s.qualified)]
        if rule.kind == EFFECTS and not rule.params["allow"]:
            replayed += covered
        elif rule.kind == MUTATION:
            mutated += [Mutated(p, rule.params["paths"], rule.params["seconds"], callees[p]) for p in covered
                        if (q := Qualified(str(p))) in ctx.declared_pure and model.symbols[q].contract
                        and ctx.is_read(q, Part.MUTANTS)  # only code whose language has its mutants made
                        and _pure(ctx.relations.effects, unknowable, p)]
        elif rule.kind == DATA_FLOW:
            protected |= protected_types(ctx, rule)[0]
    return WatchPlan(
        sources=model.files,
        tests=tuple(sorted(set(tests))),
        owners=dict(sorted(tree.unit_owner.items())),
        guarded=tuple(Guarded(t, s.owner) for t, dp in sorted(ctx.data.by_type.items())
                      if (s := ctx.data.structures[dp]).owner is not None),
        replayed=_sorted(replayed),
        protected=tuple(sorted(protected)),
        contracts=_sorted(s.place for s in operations if s.contract and ctx.is_read(s.qualified, Part.MUTANTS)),
        mutated=tuple(sorted(set(mutated), key=lambda m: str(m.place))),
    )
