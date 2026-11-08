"""What a test watcher watches (DESIGN2 §4.5), worked out from an analysis: whose each unit of code is, which
structures only their owner may change, which operations are called again to check they depend only on their
arguments, which values' text must not be written out, which contracts are run on generated inputs, and which
functions with contracts are mutated to see whether their contracts notice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from zigdag.core import codec
from zigdag.core.checks.data_rules import protected_types
from zigdag.core.checks.run import Analysis
from zigdag.core.code import CodeModel, Place, Qualified, SymbolKind
from zigdag.core.findings import RecordPath
from zigdag.core.kinds.registry import DATA_FLOW, EFFECTS, MUTATION
from zigdag.core.names import CodePath, FrName
from zigdag.core.settings import OBSERVED_FILE

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
    paths: int  # at most this many paths through the code are explored
    seconds: float  # and for at most this long


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

    def to_text(self) -> str:
        return codec.dumps(self)

    @staticmethod
    def from_text(text: str) -> WatchPlan | codec.Unreadable:
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


def plan(analysis: Analysis, tests: Iterable[RecordPath]) -> WatchPlan | None:
    """The plan for watching a project's tests; None when the code was not read."""
    ctx = analysis.context
    if ctx is None:
        return None
    model, tree = ctx.model, ctx.tree
    operations = [s for s in model.symbols.values() if s.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD)]
    replayed: list[Place] = []
    mutated: list[Mutated] = []
    unknowable = _unknowable(model)
    protected: set[Qualified] = set()
    for rule in analysis.rules:
        covered = [s.place for s in operations
                   if ctx.in_scope(rule, tree.owner(s.qualified)) and not rule.skips(tree, s.qualified)]
        if rule.kind == EFFECTS and not rule.params["allow"]:
            replayed += covered
        elif rule.kind == MUTATION:
            mutated += [Mutated(p, rule.params["paths"], rule.params["seconds"]) for p in covered
                        if (q := Qualified(str(p))) in ctx.declared_pure and model.symbols[q].contract
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
        contracts=_sorted(s.place for s in operations if s.contract),
        mutated=tuple(sorted(set(mutated), key=lambda m: str(m.place))),
    )
