"""Mutants of the pure functions that have contracts (DESIGN2 §4.5): each small edit that mutmut's operators make to
a function's body is put in place of the function's code, then the contract's cases and the tests that ran the function
are run against it. A mutant that every case and every test passes with is a change that nothing notices, unless a
bounded search finds no input it behaves differently on: then it is taken as equivalent.

mutmut's own runner never mutates a decorated function, and a deal contract is a decorator, so it would never touch
a function with a contract. Here only the body is edited: the contract stays wrapped around it, and judges it.
"""

from __future__ import annotations

import ast
import difflib
import functools
import inspect
import signal
import textwrap
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import CodeType, FunctionType

import deal

from zigdag.core.code import Cases, Mutant, MutantFate, Outcome, Place, SearchBound, TestId, Witness
from zigdag.core.findings import Digest, Span, digest_of
from zigdag.core.texts import Content
from zigdag.core.watch import Mutated
from zigdag.watchers.python import search
from zigdag.watchers.python.values import said

try:
    import libcst as cst
    from libcst.metadata import MetadataWrapper
    from mutmut.mutation.file_mutation import MutationVisitor, deep_replace
    from mutmut.mutation.mutators import mutation_operators
    from mutmut.mutation.pragma_handling import IgnoredCode
except ImportError:  # mutmut is optional: without it, no mutants are made, and the check asks why
    cst = None

UNAVAILABLE = "mutmut is not installed where the tests run: install zigdag[mutation]"
NO_TIMER = "this platform has no interval timer to stop a mutant that never returns"
TIMEOUT_FLOOR = 1.0  # seconds a mutant's cases and tests may run, at least
TIMEOUT_FACTOR = 10  # times as long as they took on the function as written

SEARCH_BACKSTOP = 3  # times its own bound in seconds that a search may run before it is stopped from outside

Rerun = Callable[[TestId], bool]  # runs one test again, quietly; whether it passed
_DIFF_CONTEXT = 1  # lines of the function shown around each edit


@dataclass(frozen=True)
class Operation:
    """A function with a contract, as the project defines it: the contract wrapped around its own code, and the class
    whose objects it runs on when it is a method or a property."""

    place: Place
    function: Callable
    owner: type | None

    @property
    def inner(self) -> FunctionType | None:
        """The function's own code, inside its contract; None for what is not a Python function."""
        inner = inspect.unwrap(self.function)
        return inner if isinstance(inner, FunctionType) else None

    @property
    def code(self) -> CodeType | None:
        inner = self.inner
        return inner.__code__ if inner is not None else None


class _TooLong(BaseException):
    """Raised by the timer inside a mutant that has run too long; a BaseException, so the mutant cannot catch it."""


@dataclass(frozen=True)
class _Edit:
    """One mutant's source: the function as written, and as edited, with its decorators left off."""

    original: str
    edited: str

    @property
    def diff(self) -> str:
        return "".join(difflib.unified_diff(self.original.splitlines(keepends=True),
                                            self.edited.splitlines(keepends=True), n=_DIFF_CONTEXT))


@deal.post(lambda result: result in (None, UNAVAILABLE, NO_TIMER))
def unavailable() -> str | None:
    """Why mutants cannot be made here, or None when they can."""
    if cst is None:
        return UNAVAILABLE
    if not hasattr(signal, "setitimer"):
        return NO_TIMER
    return None


@deal.post(lambda edit: edit.edited != edit.original)  # every mutant is a change
def _edits(source: str) -> Iterator[_Edit]:
    """Each edit mutmut's operators make to a function's body. The decorators are left off, both because mutmut
    skips decorated functions and because they are the contract, which must not change."""
    function = next(s for s in cst.parse_module(textwrap.dedent(source)).body if isinstance(s, cst.FunctionDef))
    wrapper = MetadataWrapper(cst.Module(body=[function.with_changes(decorators=[], leading_lines=[])]))
    visitor = MutationVisitor(mutation_operators, IgnoredCode(set(), set(), set()))  # markers are the check's, not ours
    wrapper.visit(visitor)
    module = wrapper.module
    bare = module.body[0]
    original = module.code_for_node(bare)
    for m in visitor.mutations:
        yield _Edit(original, module.code_for_node(deep_replace(bare, m.original_node, m.mutated_node)))


def _compiled(edit: _Edit, inner: FunctionType) -> FunctionType:
    """The edited function, compiled where the original lives, without disturbing the original's module."""
    tree = ast.parse(edit.edited)
    ast.increment_lineno(tree, inner.__code__.co_firstlineno - 1)
    scratch = dict(inner.__globals__)
    exec(compile(tree, inner.__code__.co_filename, "exec"), scratch)  # noqa: S102 (the project's own code, edited)
    return scratch[inner.__name__]


@contextmanager
@deal.pre(lambda inner, replacement: inner.__code__.co_freevars == replacement.__code__.co_freevars)  # or Python refuses
def _in_place(inner: FunctionType, replacement: FunctionType) -> Iterator[None]:
    """The replacement's code in the original function object, so whatever wraps the original runs it."""
    saved = inner.__code__, inner.__defaults__, inner.__kwdefaults__
    inner.__code__ = replacement.__code__
    inner.__defaults__, inner.__kwdefaults__ = replacement.__defaults__, replacement.__kwdefaults__
    try:
        yield
    finally:
        inner.__code__, inner.__defaults__, inner.__kwdefaults__ = saved


class _Timer:
    """Whether the time limit was reached. A test that times out is reported by pytest as a failure, so the timer
    itself is asked."""

    fired = False


@contextmanager
def _limit(seconds: float) -> Iterator[_Timer]:
    timer = _Timer()

    def stop(_signum: int, _frame: object) -> None:
        timer.fired = True
        raise _TooLong

    previous = signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield timer
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@dataclass(frozen=True)
class _Judges:
    """What a mutant is run against: the contract's cases, when inputs can be generated for it, then each test that
    ran the function, one at a time. The contract is checked on every call those tests make, too."""

    cases: Callable[[], Cases] | None  # None when no inputs can be generated: the tests judge alone
    tests: tuple[TestId, ...]
    rerun: Rerun

    def judge(self) -> tuple[MutantFate, str]:
        detail = "no inputs were generated for its contract, which held on every call of the tests that ran it"
        if self.cases is not None:
            ran = self.cases()
            if ran.outcome is Outcome.FAILED:
                return MutantFate.KILLED, f"a contract case failed: {ran.detail}"
            if not ran.generated:
                return MutantFate.NOT_RUN, ran.detail
            detail = ran.detail
        failed = next((test for test in self.tests if not self.rerun(test)), None)
        if failed is not None:
            return MutantFate.KILLED, f"{failed} failed"
        return MutantFate.SURVIVED, detail

    def passing(self) -> _Judges | None:
        """The judges that pass on the function as written, or None when there are none: its own cases fail, or
        none can be generated and no test runs it. A test that fails when it is run again is left out, since it
        cannot tell one mutant from another."""
        ran = self.cases()
        if ran.outcome is Outcome.FAILED or not (ran.generated or ran.checked_by_tests):
            return None
        tests = tuple(test for test in self.tests if self.rerun(test))
        cases = self.cases if ran.generated else None
        return _Judges(cases, tests, self.rerun) if cases is not None or tests else None


def _fate(judges: _Judges, seconds: float) -> tuple[MutantFate, str]:
    try:
        with _limit(seconds) as timer:
            fate, detail = judges.judge()
    except _TooLong:
        timer.fired = True
    if timer.fired:
        return MutantFate.TIMED_OUT, f"its contract cases and tests ran for more than {seconds:g} seconds"
    return fate, detail


def _searched(target: Mutated, operation: Operation,
              replacement: FunctionType) -> tuple[MutantFate, str, Witness | None]:
    """A survivor's fate once the search for an input it behaves differently on has run, or could not."""
    limit = SEARCH_BACKSTOP * target.seconds
    inner = operation.inner
    try:
        with _limit(limit):
            found = search.search(operation.function, inner, operation.owner,
                                  functools.partial(_in_place, inner, replacement), target.paths, target.seconds)
    except _TooLong:
        return MutantFate.SURVIVED, f"the search ran past {limit:g} seconds and was stopped", None
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:  # noqa: BLE001 (CrossHair's own errors are BaseExceptions; a failed search asks)
        return MutantFate.SURVIVED, f"the search failed ({said(e)})", None
    if found.verdict is search.Verdict.SAME:
        return MutantFate.EQUIVALENT, found.detail, None
    if found.verdict is search.Verdict.CONTRACT_FAILS:
        return MutantFate.KILLED, f"its contract fails given {found.witness.input}, an input its cases did not try", \
            found.witness
    return MutantFate.SURVIVED, found.detail, found.witness


@deal.ensure(lambda earlier, of, bound, tests, depends, result: not result or (
    bool(earlier) and all(m.of == of and m.depends == depends for m in earlier)))
def standing(earlier: tuple[Mutant, ...], of: Digest, bound: SearchBound, tests: tuple[TestId, ...],
             depends: Digest) -> bool:
    """Whether the mutants an earlier run made of a function still stand (DESIGN2 §4.5): made from the same source,
    contract included, judged by the same tests, against the same test files and the same code the function calls,
    and searched within the same bound. A change in code that the tests run but the function does not call is not
    looked for."""
    return bool(earlier) and all(
        m.of == of and m.judged_by == tests and m.bound == bound and m.depends == depends for m in earlier)


@deal.pure
def depends(callees: Digest, tests: tuple[TestId, ...], files: Mapping[TestId, Digest | None]) -> Digest:
    """What a function's mutants' fates depend on besides the function: the code it calls, and the files of the tests
    that judge them, as they are now."""
    return digest_of(callees, *(Content(f"{t}={files.get(t)}") for t in tests))


def mutants(target: Mutated, operation: Operation, span: Span, source: str, cases: Callable[[], Cases],
            tests: tuple[TestId, ...], rerun: Rerun, depended: Digest) -> list[Mutant]:
    """Every mutant of a function with a contract, each judged by the contract's cases and the tests that ran the
    function, and each survivor searched for an input it behaves differently on. None when nothing passes on the
    function as written, since then no mutant can be judged."""
    place = target.place
    inner = operation.inner
    if inner is None:
        return []
    try:
        edits = list(_edits(source))
    except (TypeError, StopIteration, cst.ParserSyntaxError) as e:  # source libcst cannot read
        return [Mutant(place, digest_of(source), "", MutantFate.NOT_RUN, f"its source could not be read ({e})",
                       span, judged_by=tests, bound=target.bound, depends=depended)]
    if not edits:  # nothing to judge, so the judges are not run
        return []
    started = time.perf_counter()
    judges = _Judges(cases, tests, rerun).passing()
    if judges is None:
        return []
    seconds = max(TIMEOUT_FLOOR, TIMEOUT_FACTOR * (time.perf_counter() - started))
    of = digest_of(source)
    out = []
    for edit in edits:
        witness = None
        try:
            replacement = _compiled(edit, inner)
            with _in_place(inner, replacement):
                fate, detail = _fate(judges, seconds)
            if fate is MutantFate.SURVIVED:
                fate, detail, witness = _searched(target, operation, replacement)
        except (SyntaxError, ValueError, TypeError, NameError) as e:  # an edit that cannot stand in for the function
            fate, detail = MutantFate.NOT_RUN, said(e)
        unnoticed = judges.tests if fate is MutantFate.SURVIVED else ()
        out.append(Mutant(place, of, edit.diff, fate, detail, span, unnoticed, witness, tests, target.bound, depended))
    return out
