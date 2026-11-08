"""The mutation rule (DESIGN2 §4.5) for functions with contracts. Each mutant is run against the contract's cases and
the tests that run the function. One that all of them pass with is a change nothing notices: a question, with the input
that shows the difference when the search found one. One the bounded search found no such input for is taken as
equivalent, and asks nothing. While such a question is open, neither the contract nor those
tests count as evidence for the statements of the function's design parameter. A marker that keeps code from being
mutated breaks, unless its function is listed under the rule's except.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from zigdag.core.checks.context import Check, Context, asked, broken
from zigdag.core.checks.rules import RuleUse
from zigdag.core.code import Link, Mutant, MutantFate, Place, Qualified, Test, TestId
from zigdag.core.findings import Finding, Result, finding
from zigdag.core.kinds.registry import MUTATION
from zigdag.core.names import CheckKindName, FrName, named_fr
from zigdag.core.record.model import EvidenceKind


def _covered(ctx: Context, rule: RuleUse, name: Qualified) -> bool:
    return ctx.in_scope(rule, ctx.tree.owner(name)) and not rule.skips(ctx.tree, name)


def _markers(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    for name, symbol in sorted(ctx.model.symbols.items()):
        if symbol.unmutated and _covered(ctx, rule, name):
            for span in symbol.unmutated:
                yield broken(rule, name, span, f"{name} marks a line not to be mutated: list {name} under the "
                             f"except of {rule.name} instead, so that leaving it out is visible", str(span.line))


def _unnoticed(m: Mutant) -> str:
    tests = len(m.unnoticed_by)
    ran = ("no test runs it" if not tests else "the one test that runs it still passes" if tests == 1
           else f"all {tests} tests that run it still pass")
    w = m.witness
    if w is not None:
        return (f"nothing notices when {m.summary} in {m.at}: given {w.input}, the code as written {w.written} and "
                f"the changed code {w.mutated}, yet its contract holds for both, and {ran}")
    return f"nothing notices when {m.summary} in {m.at}: its contract still holds, and {ran}; {m.detail}"


def _survivor(rule: RuleUse, m: Mutant) -> Finding:
    return asked(rule, str(m.at), m.span, _unnoticed(m), str(m.at), m.of, m.edit)


@dataclass(frozen=True)
class _Evidence:
    """Evidence that does not count over changes nothing noticed: a contract or a test, for one statement."""

    by: str  # what the evidence was: the contract of a function, or a test
    link: Link
    place: Place  # the function whose changes went unnoticed


def _lost(ctx: Context, unnoticed: Mapping[Place, list[Mutant]]) -> Iterator[tuple[_Evidence, int]]:
    """Each piece of evidence that ran a change nothing noticed, with how many such changes it ran. A test loses
    only its links to statements of the function's own design parameter, or one above it."""
    tests: Mapping[TestId, Test] = {t.id: t for t in ctx.model.tests}
    contracts: Mapping[Place, Test] = {t.place: t for t in ctx.model.tests
                                       if t.evidence is EvidenceKind.CONTRACT and t.place is not None}
    for place, missed in sorted(unnoticed.items()):
        owner = ctx.tree.owner_of(place)
        contract = contracts.get(place)
        for link in contract.links if contract is not None else ():
            yield _Evidence(f"the contract of {place}", link, place), len(missed)
        for test_id in sorted({t for m in missed for t in m.unnoticed_by}):
            test = tests.get(test_id)
            for link in test.links if test is not None else ():
                if owner is not None and ctx.tree.within(owner, FrName(named_fr(link.target))):
                    yield _Evidence(test_id, link, place), sum(test_id in m.unnoticed_by for m in missed)


def mutation(ctx: Context, rule: RuleUse) -> Iterable[Finding]:
    """Every change to a covered function with a contract is noticed by its contract or its tests, or answered."""
    yield from _markers(ctx, rule)
    observed = ctx.observed
    if observed.mutation_unavailable is not None:
        yield asked(rule, rule.on, rule.span, f"no mutants were made, so no contract or test was checked for changes "
                    f"it does not notice: {observed.mutation_unavailable}", observed.mutation_unavailable)
    unnoticed: dict[Place, list[Mutant]] = {}
    for m in observed.mutants:
        if not _covered(ctx, rule, Qualified(str(m.at))):
            continue
        if m.fate is MutantFate.SURVIVED:
            question = _survivor(rule, m)
            if not ctx.is_answered(question):
                unnoticed.setdefault(m.at, []).append(m)
                yield question
        elif m.fate is MutantFate.NOT_RUN:
            yield asked(rule, str(m.at), m.span, f"a mutant of {m.at} could not be run ({m.detail}), so a change "
                        f"that nothing notices may have been missed", str(m.at), m.of, m.edit)
    for evidence, count in _lost(ctx, unnoticed):
        changes = "1 change goes" if count == 1 else f"{count} changes go"
        target = evidence.link.target
        yield finding(Result.TODO, rule.name, target, evidence.link.span,
                      f"{evidence.by} does not count as evidence for {target} while {changes} unnoticed in "
                      f"{evidence.place}", target, evidence.by, str(evidence.place), str(count))


CHECKS: Mapping[CheckKindName, Check] = {MUTATION: mutation}
