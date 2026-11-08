"""The search for an input that a mutant behaves differently on (DESIGN2 §4.5). CrossHair does it: it reasons about the
code with a solver instead of guessing inputs, so "no input found" is strong evidence that the mutant changes nothing.
The search is bounded by a number of paths and a number of seconds, since a proof that two functions always agree is
out of reach in general; one that finds nothing within its bound lets the mutant be taken as equivalent.

Both versions run inside the function's own contract. An input its preconditions do not accept is no input at all,
and a version that fails its contract is told apart from one that raises any other error: a mutant that fails its
contract on an input the contract's cases never tried is noticed by the contract after all.

CrossHair is imported only when the first search runs, never while the project's tests do: importing it turns deal's
contracts off for the whole process (and icontract's), so a run that imported it early would check no contract at all.
deal is turned back on at once.
"""

from __future__ import annotations

import enum
import functools
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from types import FunctionType

from zigdag.core.code import Witness

try:
    import deal
    from deal.introspection import Pre, get_contracts
except ImportError:  # without deal there are no contracts, and nothing to search
    deal = None

UNAVAILABLE = "CrossHair is not installed where the tests run: install zigdag[mutation]"
NO_DEAL = "deal is not installed where the tests run"

Swap = Callable[[], AbstractContextManager[None]]  # puts the mutant's code in place for one call


@dataclass(frozen=True)
class _CrossHair:
    """The parts of CrossHair the search uses."""

    ignore: type[BaseException]  # raised for an input that is no input at all
    diff_behavior: Callable
    function_info: Callable
    options: object
    same_type: object  # exceptions count as the same behaviour when their types are the same


@functools.cache
def _crosshair() -> _CrossHair | None:
    """CrossHair, imported the first time a search runs; None when it is not installed."""
    try:
        from crosshair import IgnoreAttempt, core_and_libs  # noqa: F401 (registers CrossHair; it also turns deal off)
        from crosshair.diff_behavior import ExceptionEquivalenceType, diff_behavior
        from crosshair.fnutil import FunctionInfo
        from crosshair.options import DEFAULT_OPTIONS
    except ImportError:  # CrossHair is optional: without it, survivors are asked about
        return None
    finally:
        if deal is not None:
            deal.enable()  # the contracts must keep judging the mutants that are still to come
    return _CrossHair(IgnoreAttempt, diff_behavior, FunctionInfo.from_fn, DEFAULT_OPTIONS,
                      ExceptionEquivalenceType.SAME_TYPE)


class _ContractFailed(Exception):
    """A contract error, as the search sees it: one version failing its contract, told apart from any other error."""


class Verdict(enum.Enum):
    SAME = "same"  # no input within the bound behaves differently
    DIFFERENT = "different"  # an input behaves differently, and the contract accepts both versions on it
    CONTRACT_FAILS = "contract fails"  # on an input the contract's cases did not try, the mutant fails the contract
    UNSEARCHED = "unsearched"  # the search could not run


@dataclass(frozen=True)
class Searched:
    verdict: Verdict
    witness: Witness | None = None
    detail: str = ""


def _within_contract(tools: _CrossHair, function: Callable, inner: FunctionType, preconditions: list,
                     swap: Swap) -> Callable:
    """One version of the function, as the search runs it: inputs its preconditions reject are passed over, and a
    contract error becomes one error type, so that it can be told apart."""

    @functools.wraps(inner)  # CrossHair reads the signature and type hints through this
    def call(*args: object, **kwargs: object) -> object:
        for pre in preconditions:
            try:
                pre.validate(*args, **kwargs)
            except Exception:  # noqa: BLE001 (an input the contract does not accept is no input at all)
                raise tools.ignore from None
        with swap():
            try:
                return function(*args, **kwargs)
            except deal.ContractError as e:
                raise _ContractFailed(type(e).__name__) from None

    return call


def _failed(result: object) -> bool:
    """Whether one version's behaviour, as CrossHair describes it, was to fail its contract."""
    return result.error is not None and result.error.startswith(_ContractFailed.__name__)


def _witness(diff: object) -> Witness:
    shown = diff.result1.get_differing_arg_mutations(diff.result2)
    given = ", ".join(f"{name}={value}" for name, value in diff.args.items())
    return Witness(given, diff.result1.describe(shown), diff.result2.describe(shown))


def search(function: Callable, inner: FunctionType, swap: Swap, paths: int, seconds: float) -> Searched:
    """Search for an input that the function as written and the function with the mutant swapped in behave
    differently on: in what they return, what they raise, or how they change their arguments."""
    if deal is None:
        return Searched(Verdict.UNSEARCHED, detail=NO_DEAL)
    tools = _crosshair()
    if tools is None:
        return Searched(Verdict.UNSEARCHED, detail=UNAVAILABLE)
    preconditions = [c for c in get_contracts(function) if isinstance(c, Pre)]
    written = _within_contract(tools, function, inner, preconditions, nullcontext)
    mutated = _within_contract(tools, function, inner, preconditions, swap)
    options = tools.options.overlay(max_iterations=paths, per_condition_timeout=seconds)
    found = tools.diff_behavior(tools.function_info(written), tools.function_info(mutated), options,
                                tools.same_type)  # an error message is for people; its type is behaviour
    if isinstance(found, str):
        return Searched(Verdict.UNSEARCHED, detail=f"CrossHair could not search it: {found}")
    if not found:
        return Searched(Verdict.SAME, detail=f"no input behaves differently within {paths} paths and {seconds:g} "
                                             f"seconds of search")
    caught = next((d for d in found if _failed(d.result2) and not _failed(d.result1)), None)
    if caught is not None:
        return Searched(Verdict.CONTRACT_FAILS, _witness(caught))
    return Searched(Verdict.DIFFERENT, _witness(found[0]))
