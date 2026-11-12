"""Evidence (DESIGN2 §4.3, §4.5): which tests verify which statements, and whether each counts as evidence.

A statement has evidence when a linked test of every kind it needs passed in the latest report. After `zigdag test`,
a test also must have run code in the statement's DP, against the code as it is now; a contract must hold on its
generated inputs. Before it, whether a test runs the DP's code is a guess from what it imports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import deal

from zigdag.core.code import CodeModel, Observations, Outcome, Run, Test, TestId
from zigdag.core.findings import Digest, Finding, Result, Span, Subject, finding
from zigdag.core.language.performance import bounds
from zigdag.core.names import FrName, Revision, is_within
from zigdag.core.record.model import EvidenceKind, Record, Verification
from zigdag.core.resolve import Tree
from zigdag.core.settings import DEFAULT_REPORT
from zigdag.core.texts import Content, Say

EVIDENCE = "evidence"
LINKS = "evidence.links"
REPORTS = "evidence.reports"
OBSERVATIONS = "observations"
EVIDENCE_RULES = frozenset({EVIDENCE, LINKS, REPORTS})
TEST_COMMAND = "zigdag test"
TESTS_SUBJECT = "tests"  # what a finding about the project's tests as a whole is about

@dataclass(frozen=True)
class Stated:
    """A statement as the record states it: an FR's, or a constraint's."""

    ref: str  # fr#statement, or a constraint's name
    dp: FrName
    text: str
    span: Span


@deal.ensure(lambda record, result: [s.ref for s in result] == sorted(s.ref for s in result))
def stated(record: Record) -> list[Stated]:
    """Every statement in the record, FRs' and constraints', by reference."""
    out = [Stated(str(s.ref), name, s.sentence.text, s.sentence.span)
           for name, fr in record.frs.items() for s in fr.statements]
    out += [Stated(name, c.on.value, c.statement.text, c.statement.span)
            for name, c in record.constraints.items() if c.statement is not None]
    return sorted(out, key=lambda s: s.ref)


def _needed(record: Record, statement: Stated) -> set[EvidenceKind]:
    kinds = {EvidenceKind.BENCHMARK} if bounds(statement.text) else set()  # one that bounds performance
    for v in record.process.values():
        if isinstance(v.kind, Verification) and v.kind.evidence is not EvidenceKind.TEST_REPORT and is_within(
                statement.dp, v.on.value):
            kinds.add(v.kind.evidence)
    return kinds


def _imports_code_in(test: Test, dp: FrName, tree: Tree, model: CodeModel) -> bool:
    return any((owner := tree.owner(i)) is not None and tree.within(owner, dp) for i in test.imports if
               model.unit_of(i) is not None)


def _ran_code_in(run: Run, dp: FrName, tree: Tree) -> bool:
    return any((owner := tree.owner(unit)) is not None and tree.within(owner, dp) for unit in run.ran)


def _unwatched_in(observed: Observations, dp: FrName, tree: Tree) -> bool:
    """Whether some of a DP's code is code the watcher cannot see run: its own."""
    return any((owner := tree.owner(unit)) is not None and tree.within(owner, dp) for unit in observed.unwatched)


def _outcome(t: Test, model: CodeModel, observed: Observations) -> tuple[Outcome | None, str]:
    """A test's latest result, and what it says; a contract's comes from its generated cases, or from the tests that
    called it when no inputs could be generated, or holds until run."""
    if t.evidence is not EvidenceKind.CONTRACT:
        outcome = model.results.get(t.id)
        return outcome, outcome.value if outcome else ""
    cases = observed.cases_of(t.place)
    if cases is None:
        return Outcome.PASSED, ""
    if cases.checked_by_tests:
        failed = [test for test in cases.called_by if model.results.get(test) in (Outcome.FAILED, Outcome.ERROR)]
        if failed:
            return Outcome.FAILED, f"on the calls of {failed[0]}, which failed"
        return Outcome.PASSED, ""
    if not cases.generated:
        return Outcome.ERROR, f"on generated inputs, and no test calls it: {cases.detail}"
    return cases.outcome, f"on generated inputs: {cases.detail}"


def check_evidence(record: Record, model: CodeModel, tree: Tree) -> Iterable[Finding]:
    statements = stated(record)
    known = {s.ref: s for s in statements}
    linked: dict[str, list[Test]] = {}
    for test in model.tests:
        for link in test.links:
            if link.target not in known:
                yield finding(Result.BREAKS, LINKS, test.id, link.span,
                              f'{test.id} verifies "{link.target}", which is no statement or constraint statement',
                              link.target)
            else:
                linked.setdefault(link.target, []).append(test)
    observed = model.observed or Observations()
    if linked and not model.reports_read:
        yield finding(Result.OUT_OF_DATE, REPORTS, TESTS_SUBJECT, None,
                      f"no test report was read: run {TEST_COMMAND}, or the tests with --junitxml={DEFAULT_REPORT}")
    if observed.stale:
        yield finding(Result.OUT_OF_DATE, OBSERVATIONS, TESTS_SUBJECT, None,
                      f"{observed.stale} things seen while the tests ran are about code that has changed since, and "
                      f"are left out: run {TEST_COMMAND}", str(observed.stale))
    for s in statements:
        tests = sorted(linked.get(s.ref, ()), key=lambda t: t.id)
        if not tests:
            yield finding(Result.TODO, EVIDENCE, s.ref, s.span, f"no test verifies {s.ref}")
            continue
        passed = []
        for t in tests:
            outcome, said = _outcome(t, model, observed)
            run = observed.run_of(t.id)
            if outcome is Outcome.ERROR and t.evidence is EvidenceKind.CONTRACT:
                yield finding(Result.QUESTION, EVIDENCE, s.ref, t.span, f"{t.id} could not be run {said}", t.id)
            elif outcome in (Outcome.FAILED, Outcome.ERROR):
                how = outcome.value if said == outcome.value else f"{outcome.value} {said}".rstrip()
                yield finding(Result.BREAKS, EVIDENCE, s.ref, t.span, f"{t.id} {how}, so {s.ref} has no evidence",
                              t.id, outcome.value)
            elif outcome is Outcome.PASSED and run is not None and not run.current:
                yield finding(Result.OUT_OF_DATE, EVIDENCE, s.ref, t.span, f"{t.id} passed against code that has changed "
                              f"since: run {TEST_COMMAND}", t.id)
            elif outcome is Outcome.PASSED:
                passed.append(t)
            elif model.reports_read:
                yield finding(Result.TODO, EVIDENCE, s.ref, t.span, f"{t.id} has not run, or was skipped", t.id)
            if t.evidence is EvidenceKind.CONTRACT:
                continue
            if run is not None and run.current and not _ran_code_in(run, s.dp, tree) and run.processes:
                yield finding(Result.QUESTION, EVIDENCE, s.ref, t.span, f"{t.id} ran no code in {s.dp} in its own "
                              f"process, and started others, which cannot be watched", t.id)
            elif run is not None and run.current and not _ran_code_in(run, s.dp, tree) and _unwatched_in(
                    observed, s.dp, tree):
                yield finding(Result.QUESTION, EVIDENCE, s.ref, t.span, f"{t.id} ran no code in {s.dp} that could be "
                              f"watched: the watcher cannot see its own code run", t.id)
            elif run is not None and run.current and not _ran_code_in(run, s.dp, tree):
                yield finding(Result.BREAKS, EVIDENCE, s.ref, t.span, f"{t.id} ran no code in {s.dp} when it last "
                              f"ran, so it is linked to the wrong thing", t.id)
            elif run is None and not _imports_code_in(t, s.dp, tree, model):
                yield finding(Result.QUESTION, EVIDENCE, s.ref, t.span,
                              f"{t.id} imports nothing from {s.dp}, so it may not run the code it verifies", t.id)
        for kind in sorted(_needed(record, s) - {t.evidence for t in passed}, key=lambda k: k.value):
            yield finding(Result.TODO, EVIDENCE, s.ref, s.span, f"{s.ref} needs {kind.value} evidence that passed",
                          kind.value)


def _verifying(tests: Sequence[Test], ref: str) -> Mapping[TestId, Digest | None]:
    """The tests that say they verify a statement, each with the digest of its source."""
    return {t.id: t.source for t in tests if any(link.target == ref for link in t.links)}


def _unanswered(before: Record, tests_before: Sequence[Test], after: Record,
                tests_after: Sequence[Test]) -> list[Stated]:
    """The statements a change added or changed that no test it added or changed verifies. A test whose source the
    adapter does not give is taken to have changed: zigdag cannot say it did not."""
    was = {s.ref: s.text for s in stated(before)}
    out = []
    for s in stated(after):
        now, then = _verifying(tests_after, s.ref), _verifying(tests_before, s.ref)
        if was.get(s.ref) != s.text and all(source is not None and then.get(test) == source
                                            for test, source in now.items()):
            out.append(s)
    return out


@deal.post(lambda found: found.result is Result.TODO and found.rule == EVIDENCE)
def unanswered(before: Record, tests_before: Sequence[Test], after: Record,
               tests_after: Sequence[Test]) -> Iterable[Finding]:
    """A thing to do for each statement a change added or changed that no test it added or changed verifies: what
    the change asks for and has not been given yet. Whether a test passes is not asked, so this says the same of a
    revision whose tests never ran as of a folder where they did."""
    for s in _unanswered(before, tests_before, after, tests_after):
        yield finding(Result.TODO, EVIDENCE, Subject(s.ref), s.span,
                      Say(f"needs a test of what it says now: {s.text}"), Content(s.text))


@deal.post(lambda found: found.result is Result.TODO and found.rule == EVIDENCE)
def check_changed(before: Record, tests_before: Sequence[Test], after: Record, tests_after: Sequence[Test],
                  base: Revision) -> Iterable[Finding]:
    """A thing to do for each statement that says something else than it did at the base of a change, while every
    test that verifies it is as it was there. Such a test passed for the old sentence, and its passing says nothing
    of the new one. A statement no test verifies is left to check_evidence, which reports it with or without a
    base."""
    known = {s.ref for s in stated(before)}
    for s in _unanswered(before, tests_before, after, tests_after):
        if s.ref in known and _verifying(tests_after, s.ref):
            yield finding(Result.TODO, EVIDENCE, s.ref, s.span,
                          f"{s.ref} changed since {base}, and no test that verifies it has: change a test to fit "
                          f"what it says now, or add one", s.text)
