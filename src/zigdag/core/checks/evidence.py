"""Evidence (DESIGN2 §4.3, §4.5): which tests verify which statements, and whether each counts as evidence.

A statement has evidence when a linked test of every kind it needs passed in the latest report. After `zigdag test`,
a test also must have run code in the statement's DP, against the code as it is now; a contract must hold on its
generated inputs. Before it, whether a test runs the DP's code is a guess from what it imports.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from zigdag.core.code import CodeModel, Observations, Outcome, Run, Test
from zigdag.core.findings import Finding, Result, Span, finding
from zigdag.core.language.tokens import tokenize, words
from zigdag.core.names import FrName, is_within
from zigdag.core.record.model import EvidenceKind, Record, Verification
from zigdag.core.resolve import Tree
from zigdag.core.settings import DEFAULT_REPORT

EVIDENCE = "evidence"
LINKS = "evidence.links"
REPORTS = "evidence.reports"
OBSERVATIONS = "observations"
EVIDENCE_RULES = frozenset({EVIDENCE, LINKS, REPORTS})
TEST_COMMAND = "zigdag test"
TESTS_SUBJECT = "tests"  # what a finding about the project's tests as a whole is about

_TIME_UNITS = frozenset({"s", "sec", "second", "seconds", "ms", "millisecond", "milliseconds", "us", "ns", "min",
                         "minute", "minutes", "h", "hour", "hours"})
_BOUNDS = ("within", "under", "at most", "less than", "up to")


@dataclass(frozen=True)
class _Statement:
    ref: str  # fr#statement, or a constraint's name
    dp: FrName
    text: str
    span: Span


def _statements(record: Record) -> list[_Statement]:
    out = [_Statement(str(s.ref), name, s.sentence.text, s.sentence.span)
           for name, fr in record.frs.items() for s in fr.statements]
    out += [_Statement(name, c.on.value, c.statement.text, c.statement.span)
            for name, c in record.constraints.items() if c.statement is not None]
    return sorted(out, key=lambda s: s.ref)


def _time_bound(text: str) -> bool:
    w = words(tokenize(text))
    joined = f" {' '.join(w)} "
    return any(f" {b} " in joined for b in _BOUNDS) and any(u in w for u in _TIME_UNITS) and any(
        t.is_number for t in tokenize(text))


def _needed(record: Record, statement: _Statement) -> set[EvidenceKind]:
    kinds = {EvidenceKind.BENCHMARK} if _time_bound(statement.text) else set()
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
    """A test's latest result, and what it says; a contract's comes from its generated cases, or holds until run."""
    if t.evidence is not EvidenceKind.CONTRACT:
        outcome = model.results.get(t.id)
        return outcome, outcome.value if outcome else ""
    cases = observed.cases_of(t.place)
    if cases is None:
        return Outcome.PASSED, ""
    return cases.outcome, f"on generated inputs: {cases.detail}"


def check_evidence(record: Record, model: CodeModel, tree: Tree) -> Iterable[Finding]:
    statements = _statements(record)
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
        yield finding(Result.TODO, REPORTS, TESTS_SUBJECT, None,
                      f"no test report was read: run {TEST_COMMAND}, or the tests with --junitxml={DEFAULT_REPORT}")
    if observed.stale:
        yield finding(Result.TODO, OBSERVATIONS, TESTS_SUBJECT, None,
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
                yield finding(Result.TODO, EVIDENCE, s.ref, t.span, f"{t.id} passed against code that has changed "
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
