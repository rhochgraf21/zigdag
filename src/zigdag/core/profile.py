"""A profile of the tests (DESIGN2 §4.7): where their time and memory went, line by line, as the adapter's profiler
measured it, summed up by design part. A view only: it never breaks and never asks, since a profile says where cost
is, and only a bound written down says a cost is too much."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import deal

from zigdag.core.code import CodeModel
from zigdag.core.findings import RecordPath, Span
from zigdag.core.measures import Growth, Likelihood, Megabytes, Seconds, Share
from zigdag.core.names import FrName
from zigdag.core.resolve import Tree
from zigdag.core.texts import Say

TESTS = Say("the tests")  # where a test's own lines go
OUTSIDE = Say("outside the project")  # where libraries' lines go, the test runner's among them


@dataclass(frozen=True)
class ProfiledLine:
    span: Span
    time: Share  # of all the time the profiled run took
    allocated: Megabytes  # all the memory the line allocated


@dataclass(frozen=True)
class Leak:
    """A line the profiler suspects of leaking: what it allocates is seldom freed."""

    span: Span
    likelihood: Likelihood  # that it leaks, as the profiler judges it
    growth: Growth  # how fast the memory it holds grows


@dataclass(frozen=True)
class Profile:
    elapsed: Seconds
    peak: Megabytes | None  # the most memory the run held at once; None when the profiler measures no memory
    lines: tuple[ProfiledLine, ...]
    leaks: tuple[Leak, ...] = ()

    @deal.ensure(lambda self, share, result: result >= 0)
    def seconds(self, share: Share) -> Seconds:
        """The time a share of the run is: the profiler gives each line its share of the time the run took."""
        return Seconds(share / _WHOLE * self.elapsed)


@dataclass(frozen=True)
class Cost:
    """What one part of the project cost in a profiled run: a design parameter, the tests, or what is outside."""

    part: Say
    time: Share
    seconds: Seconds  # the CPU time that share is
    allocated: Megabytes


@dataclass(frozen=True)
class Suspect:
    """A suspected leak, with the part of the project whose code it is."""

    leak: Leak
    part: Say


_ROUNDING = 1e-6  # how far sums of the same shares may differ, added up in another order
_WHOLE = 100  # a share is a percentage


@deal.ensure(lambda profile, model, tree, tests, result: abs(sum(c.time for c in result) - sum(
    line.time for line in profile.lines)) < _ROUNDING)  # every line counted once
@deal.ensure(lambda profile, model, tree, tests, result: [c.time for c in result] == sorted(
    (c.time for c in result), reverse=True))  # most first
def by_part(profile: Profile, model: CodeModel, tree: Tree, tests: tuple[RecordPath, ...]) -> tuple[Cost, ...]:
    """Each design parameter's cost, with what the tests and what is outside the project cost, the costliest first.
    A line counts for the design parameter whose code it is."""
    time: dict[str, float] = {}
    allocated: dict[str, float] = {}
    for line in profile.lines:
        part = _part(line.span, model, tree, tests)
        time[part] = time.get(part, 0.0) + line.time
        allocated[part] = allocated.get(part, 0.0) + line.allocated
    return tuple(sorted((Cost(Say(p), Share(t), profile.seconds(Share(t)), Megabytes(allocated[p]))
                         for p, t in time.items()), key=lambda c: (-c.time, c.part)))


def _part(span: Span, model: CodeModel, tree: Tree, tests: tuple[RecordPath, ...]) -> Say:
    """The part of the project a line is: the design parameter whose code it is, the tests, or what is outside."""
    name = model.code_at(span)
    owner: FrName | None = tree.owner(name) if name is not None else None
    return Say(owner or (TESTS if any(span.path.startswith(f"{t}/") for t in tests) else OUTSIDE))


@deal.ensure(lambda profile, model, tree, tests, result: len(result) == len(profile.leaks))
@deal.ensure(lambda profile, model, tree, tests, result: [s.leak.likelihood for s in result] == sorted(
    (s.leak.likelihood for s in result), reverse=True))  # likeliest first
def suspects(profile: Profile, model: CodeModel, tree: Tree, tests: tuple[RecordPath, ...]) -> tuple[Suspect, ...]:
    """Each leak the profiler suspects, with the part of the project it is in, the likeliest first."""
    return tuple(sorted((Suspect(leak, _part(leak.span, model, tree, tests)) for leak in profile.leaks),
                        key=lambda s: (-s.leak.likelihood, s.leak.span)))


@dataclass(frozen=True)
class Comparison:
    """One part's cost in the latest profiled run, and in the run before it, when it was there."""

    now: Cost
    before: Cost | None


@deal.ensure(lambda now, before, result: [c.now for c in result] == list(now))
def compared(now: tuple[Cost, ...], before: tuple[Cost, ...]) -> tuple[Comparison, ...]:
    """Each part of the latest run, beside what it cost the run before."""
    earlier: Mapping[str, Cost] = {c.part: c for c in before}
    return tuple(Comparison(c, earlier.get(c.part)) for c in now)
