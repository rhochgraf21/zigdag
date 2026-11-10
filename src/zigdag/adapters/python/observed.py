"""What the Python watcher saw while the tests ran, as it hands it over, and the part of it that is still current.

An observation counts only while every file it was seen in is unchanged: a run shows what the code did then.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import deal

from zigdag.core import codec
from zigdag.core.code import (
    Access,
    Call,
    Cases,
    Crossing,
    Dependency,
    EffectStart,
    Escape,
    Leak,
    Mutant,
    Observations,
    Place,
    Qualified,
    Replay,
    Run,
    TestId,
)
from zigdag.core.findings import Digest, RecordPath
from zigdag.core.names import CodePath
from zigdag.core.texts import FileText, Say
from zigdag.core.watch import LastRun

COLLECTION = TestId("(collecting the tests)")  # what is seen before any test runs, while test modules are imported


@dataclass(frozen=True)
class Ran:
    """One test, and the units whose code ran while it did."""

    test: TestId
    file: RecordPath
    ran: frozenset[CodePath]
    processes: bool = False  # it started other processes, whose code could not be watched


@dataclass(frozen=True)
class Recording:
    """Everything one watched run of the tests saw."""

    files: Mapping[RecordPath, Digest]  # every source and test file, as it was when the run started
    runs: tuple[Ran, ...] = ()
    effects: tuple[EffectStart, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    calls: tuple[Call, ...] = ()
    accesses: tuple[Access, ...] = ()
    crossings: tuple[Crossing, ...] = ()
    escapes: tuple[Escape, ...] = ()
    leaks: tuple[Leak, ...] = ()
    replays: tuple[Replay, ...] = ()
    cases: tuple[Cases, ...] = ()
    mutants: tuple[Mutant, ...] = ()
    mutation_unavailable: Say | None = None  # why no mutants were made
    unwatched: tuple[CodePath, ...] = ()  # units whose running the watcher cannot see: its own

    @deal.ensure(lambda self, result: Recording.from_text(result) == self)  # zigdag reads back what the watcher saw
    def to_text(self) -> FileText:
        return codec.dumps(self)

    @property
    @deal.ensure(lambda self, result: result.mutants == self.mutants)
    def for_next_run(self) -> LastRun:
        """What the next run carries mutants over from: the mutants this run made."""
        return LastRun(self.mutants)

    @staticmethod
    @deal.post(lambda result: isinstance(result, Recording | codec.Unreadable))
    def from_text(text: FileText) -> Recording | codec.Unreadable:
        return codec.loads(Recording, text)


@dataclass(frozen=True)
class Observed:
    """The current part of a recording, ready to join the code model."""

    effects: tuple[EffectStart, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    calls: tuple[Call, ...] = ()
    accesses: tuple[Access, ...] = ()
    observations: Observations = field(default_factory=Observations)


@dataclass(frozen=True)
class _Currency:
    """Which files are as they were when the run started."""

    then: Mapping[RecordPath, Digest]
    now: Mapping[RecordPath, Digest]
    files_of: Mapping[CodePath, RecordPath]

    def file(self, path: RecordPath) -> bool:
        return path in self.now and self.then.get(path) == self.now[path]

    def unit(self, unit: CodePath) -> bool:
        path = self.files_of.get(unit)
        return path is not None and self.file(path)

    def place(self, place: Place | None) -> bool:
        return place is None or self.unit(place.unit)

    def name(self, name: Qualified) -> bool:
        """A name inside the project is current with its unit; one outside the project always is."""
        parts = name.split(".")
        units = [CodePath(".".join(parts[:i])) for i in range(len(parts), 0, -1)]
        unit = next((u for u in units if u in self.files_of), None)
        return unit is None or self.unit(unit)


def current(recording: Recording, now: Mapping[RecordPath, Digest],
            files_of: Mapping[CodePath, RecordPath]) -> Observed:
    c = _Currency(recording.files, now, files_of)
    effects = tuple(e for e in recording.effects if c.place(e.at) and c.file(e.span.path))
    dependencies = tuple(d for d in recording.dependencies if c.place(d.source) and c.name(d.target))
    calls = tuple(x for x in recording.calls if c.place(x.caller) and c.name(x.callee))
    accesses = tuple(a for a in recording.accesses if c.place(a.at) and c.name(a.value.root))
    crossings = tuple(x for x in recording.crossings if c.place(x.at) and c.file(x.span.path))
    escapes = tuple(x for x in recording.escapes if c.place(x.at) and c.file(x.span.path))
    leaks = tuple(x for x in recording.leaks if c.place(x.at) and c.name(x.data))
    replays = tuple(x for x in recording.replays if c.place(x.at))
    cases = tuple(x for x in recording.cases if c.place(x.at))
    test_files = {r.test: r.file for r in recording.runs}
    mutants = tuple(x for x in recording.mutants  # a survivor goes out of date with the tests that missed it, too
                    if c.place(x.at) and all(c.file(test_files[t]) for t in x.unnoticed_by if t in test_files))
    runs = {r.test: Run(r.test, r.ran, c.file(r.file) and all(c.unit(u) for u in r.ran), r.processes)
            for r in recording.runs}
    kept = sum(len(x) for x in (effects, dependencies, calls, accesses, crossings, escapes, leaks, replays, cases,
                                mutants))
    total = sum(len(x) for x in (recording.effects, recording.dependencies, recording.calls, recording.accesses,
                                 recording.crossings, recording.escapes, recording.leaks, recording.replays,
                                 recording.cases, recording.mutants))
    return Observed(effects, dependencies, calls, accesses,
                    Observations(runs, crossings, escapes, leaks, replays, cases, mutants,
                                 mutation_unavailable=recording.mutation_unavailable,
                                 unwatched=recording.unwatched, stale=total - kept))
