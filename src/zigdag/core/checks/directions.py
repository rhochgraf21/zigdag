"""How each direction of code quality stands (DESIGN2 §4.6): its findings, and whether its rules could run, so the
report can end each direction as a linter ends its run, with whether all its checks passed."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import deal

from zigdag.core.checks.code_rules import CANT_TELL, CONTRACTS, DECLARED_EFFECTS
from zigdag.core.checks.data_rules import FEATURE, STATE
from zigdag.core.checks.evidence import EVIDENCE, LINKS, OBSERVATIONS, REPORTS
from zigdag.core.checks.part_rules import SETTLED_FIRST, STAY_IN_PART
from zigdag.core.checks.record_rules import ADAPTER, registry
from zigdag.core.checks.run import EXCEPT, Analysis
from zigdag.core.checks.tool_rules import DIAGNOSES, tolerated
from zigdag.core.code import TOOL_FAILED, Diagnosis
from zigdag.core.findings import Finding, Report, Result, RuleName
from zigdag.core.kinds.registry import Direction, Part
from zigdag.core.measures import Count
from zigdag.core.names import RuleId
from zigdag.core.resolve import COVERAGE, LEVELS, PLACEMENT
from zigdag.core.texts import Say

# zigdag's own rules that are no check kind, by what they judge. Every other one of them, from the grammar of a
# statement to a workflow gate, is about the design itself.
_OWN: Mapping[RuleName, Direction] = {
    RuleName(EVIDENCE): Direction.CORRECTNESS,
    RuleName(LINKS): Direction.CORRECTNESS,
    RuleName(REPORTS): Direction.CORRECTNESS,
    RuleName(OBSERVATIONS): Direction.CORRECTNESS,
    RuleName(CONTRACTS): Direction.CORRECTNESS,
    RuleName(DECLARED_EFFECTS): Direction.ARCHITECTURE,
    RuleName(CANT_TELL): Direction.ARCHITECTURE,
    RuleName(STATE): Direction.ARCHITECTURE,
    RuleName(FEATURE): Direction.ARCHITECTURE,
    RuleName(ADAPTER): Direction.ARCHITECTURE,
    RuleName(COVERAGE): Direction.ARCHITECTURE,  # code that no design parameter is
    RuleName(LEVELS): Direction.ARCHITECTURE,  # code at a level the tree does not allow
    RuleName(PLACEMENT): Direction.ARCHITECTURE,  # a placement that names no code
    RuleName(EXCEPT): Direction.ARCHITECTURE,  # an except that names no code
    STAY_IN_PART: Direction.ARCHITECTURE,  # a part's branch changed a file that is not the part's
    SETTLED_FIRST: Direction.ARCHITECTURE,  # a part's branch changed what other parts are built against
}
_DESIGNED = Direction.DESIGN  # the one direction that needs no code: its checks always run
_DIAGNOSED: Mapping[Diagnosis, Direction] = {Diagnosis.LINT: Direction.LINT, Diagnosis.TYPES: Direction.TYPECHECK,
                                             Diagnosis.SECURITY: Direction.SECURITY}
COUNTED: Mapping[Result, tuple[Say, Say]] = {Result.BREAKS: (Say("break"), Say("breaks")),
                                             Result.QUESTION: (Say("question"), Say("questions")),
                                             Result.OUT_OF_DATE: (Say("result out of date"), Say("results out of date")),
                                             Result.TODO: (Say("thing to do"), Say("things to do"))}
PASSED = Say("All checks passed!")  # as ruff and ty say it
NOT_CHECKED = Say("Not checked")


@deal.ensure(lambda kind, n, result: result.startswith(f"{n} ") and result.endswith(COUNTED[kind][n != 1]))
def counted(kind: Result, n: Count) -> Say:
    """A number of findings of one result, as a sentence counts them: 1 break, 2 questions."""
    one, many = COUNTED[kind]
    return Say(f"{n} {one if n == 1 else many}")


def _are(n: Count, one: str, many: str, what: str) -> Say:
    return Say(f"1 {one} is {what}" if n == 1 else f"{n} {many} are {what}")


def _and(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


@dataclass(frozen=True)
class Standing:
    """One direction of code quality, as one run found it."""

    direction: Direction
    findings: tuple[Finding, ...]  # in the report's order
    read: bool  # the code was read: only the record is checked without it
    rules: tuple[RuleId, ...]  # its rules in force
    waiting: tuple[RuleId, ...]  # those of them this run could not check
    missing: tuple[Part, ...]  # what those wait for, which no adapter supplied
    excepted: Count  # entries under the except of its rules: the code they leave unchecked
    tolerated: Count  # diagnoses a linter or type checker made on that code

    @property
    @deal.ensure(lambda self, result: result == (not self.findings and (
        self.direction is _DESIGNED or (self.read and len(self.waiting) < len(self.rules)))))
    def passed(self) -> bool:
        """Whether every check of it that ran found nothing, and at least one could run. The design's always run."""
        if self.findings:
            return False
        if self.direction is _DESIGNED:
            return True
        return self.read and bool(self.rules) and len(self.waiting) < len(self.rules)

    @property
    @deal.ensure(lambda self, result: (result == PASSED) == self.passed and (result == NOT_CHECKED) == (
        not self.passed and not self.findings))
    def status(self) -> Say:
        """How it stands, in a few words, as ruff and ty end a run: all passed, what was found, or not checked."""
        if self.findings:
            found = [counted(r, Count(n)) for r in COUNTED if (n := sum(f.result is r for f in self.findings))]
            return Say(f"Found {_and(found)}")
        return PASSED if self.passed else NOT_CHECKED

    @property
    @deal.ensure(lambda self, result: not self.findings or result == ())
    @deal.ensure(lambda self, result: self.passed or bool(self.findings) or bool(result))  # not checked says why
    def notes(self) -> tuple[Say, ...]:
        """What qualifies the status, when nothing was found: why it was not checked, or what a pass leaves out."""
        if self.findings:
            return ()
        if self.direction is not _DESIGNED and not self.read:
            return (Say("no code was read"),)
        if self.direction is not _DESIGNED and not self.rules:
            return (Say("no rule of it is in force"),)
        if self.passed:
            return (*((self._waits,) if self.waiting else ()),
                    *((_are(self.tolerated, "diagnostic", "diagnostics", "in excepted code"),) if self.tolerated else
                      (_are(self.excepted, "place", "places", "excepted"),) if self.excepted else ()))
        return (self._waits,)

    @property
    @deal.ensure(lambda self, result: len(result) == len(self.notes))
    def brief(self) -> tuple[Say, ...]:
        """Its notes, short enough for a table: rules that wait are only counted."""
        if not self.waiting:
            return self.notes
        waits = Say("1 rule waits" if len(self.waiting) == 1 else f"{len(self.waiting)} rules wait")
        return tuple(waits if n == self._waits else n for n in self.notes)

    @property
    @deal.ensure(lambda self, result: result.startswith(PASSED) == self.passed)
    def verdict(self) -> Say:
        """How it stands, in one sentence: its status, then its notes."""
        if not self.passed and self.notes:
            return Say(f"{self.status}: {'; '.join(self.notes)}.")
        return Say(" ".join([f"{self.status}." if self.findings else self.status,
                             *(f"{n[0].upper()}{n[1:]}." for n in self.notes)]))

    @property
    def _waits(self) -> Say:
        wait = "waits" if len(self.waiting) == 1 else "wait"
        return Say(f"{_and(list(self.waiting))} {wait} for {_and([p.value for p in self.missing])}, which no adapter "
                   f"read")


def _direction(f: Finding, of_rule: Mapping[RuleName, Direction]) -> Direction:
    if f.rule == TOOL_FAILED:  # about what the tool diagnoses
        return _DIAGNOSED.get(next((d for d in Diagnosis if d.value == f.about), None), _DESIGNED)
    return of_rule.get(f.rule) or _OWN.get(f.rule, _DESIGNED)


@deal.ensure(lambda a, report, result: [s.direction for s in result] == list(Direction))
@deal.ensure(lambda a, report, result: sum(len(s.findings) for s in result) == len(report.findings))  # each once
def standings(a: Analysis, report: Report) -> tuple[Standing, ...]:
    """Each direction of code quality, in the report's order, with its findings from the report: the analysis's own,
    or with the gates of a change added."""
    kinds = registry(a.settings)
    of_rule = {RuleName(r.name): kinds[r.kind].direction for r in a.rules if r.kind in kinds}
    unchecked, supplied = a.unchecked, a.code.supplied if a.code is not None else frozenset()
    ctx = a.context
    out = []
    for direction in Direction:
        rules = [r for r in a.rules if r.kind in kinds and kinds[r.kind].direction is direction]
        waiting = [r for r in rules if r.name in unchecked]
        missing = sorted({p for r in waiting for p in kinds[r.kind].reads - supplied}, key=lambda p: p.value)
        tools = [r for r in rules if r.kind in DIAGNOSES and r.name not in unchecked]
        out.append(Standing(
            direction, tuple(f for f in report.findings if _direction(f, of_rule) is direction), a.code is not None,
            tuple(r.name for r in rules), tuple(r.name for r in waiting), tuple(missing),
            Count(sum(len(r.excepted) for r in rules)),
            Count(sum(tolerated(ctx, r) for r in tools) if ctx is not None else 0)))
    return tuple(out)
