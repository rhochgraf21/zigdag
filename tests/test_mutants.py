"""Mutants of functions with contracts (DESIGN2 §4.5): zigdag test edits each function's body with mutmut's
operators, and runs the contract's cases and the tests that run the function against every edit. An edit that
nothing notices is asked about, and the contract and the tests that missed it stop counting as evidence until it is
killed or answered."""

import functools
import json
import sys
from pathlib import Path

import deal
from test_code import found, run

from zigdag import verifies
from zigdag.cli import main
from zigdag.core.code import MutantFate, Outcome
from zigdag.core.findings import Result
from zigdag.core.log import Actor, Answer, Timestamp, answered_question
from zigdag.watchers.python import search
from zigdag.watchers.python.mutants import _in_place

PATHS, SECONDS = 200, 10.0  # the mutation rule's own bounds

SETTINGS = f"""[settings]
ruleset = 1
test_command = "{sys.executable} -m pytest -q -p no:cacheprovider"
[adapters]
default = "python"
[adapters.python]
source = ["src"]
"""
PYPROJECT = ('[project]\nname = "calc"\ndependencies = ["deal", "zigdag"]\n'
             '[tool.pytest.ini_options]\npythonpath = ["src"]\n')
CUSTOMER = """
add-up:
  job: Add up a bill
  performer: Cashier
  outcomes:
    wrong-total: Minimize the likelihood that a bill is added up wrong
"""
FUNCTIONAL = """
frs:
  calc:
    statements:
      sum: The calc shall add up numbers.
  calc.maths:
    serves: [add-up.wrong-total]
    statements:
      sum: The maths shall add two numbers.
      difference: When asked for a difference, the maths shall return the difference of two numbers.
      product: When asked for a product, the maths shall return the product of two numbers.
"""
MATHS = '''"""Arithmetic, with contracts of different strength. Only what is declared pure is mutated."""
import os
from dataclasses import dataclass

import deal

from zigdag import verifies


@verifies("calc.maths#sum")
@deal.has()
@deal.post(lambda result: result is not None)
def add(a: int, b: int) -> int:
    """The sum. Its contract says little, but its test says exactly what the sum is."""
    return a + b


@verifies("calc.maths#difference")
@deal.has()
@deal.post(lambda result: result is not None)
def subtract(a: int, b: int) -> int:
    """The difference. Its contract and its test both say little."""
    return a - b


@deal.pure
@deal.post(lambda result: result is not None)
def negate(n: int) -> int:
    """The negative. Its contract says little, and no test runs it."""
    return -n


@verifies("calc.maths#product")
@deal.has()
@deal.ensure(lambda a, b, result: result == a * b)
def times(a: int, b: int) -> int:
    """The product. Its contract says exactly what the result is, so it notices every change on its own."""
    return a * b


@deal.has()
@deal.post(lambda result: result >= 0)
def size(n: int) -> int:
    """How far n is from zero."""
    return abs(n)  # pragma: no mutate


@deal.has()
@deal.post(lambda result: result >= 0)
def clamp(n: int) -> int:
    """n, or 0 for a negative n. Changing `n < 0` to `n <= 0` makes no difference, since 0 is 0 either way."""
    if n < 0:
        return 0
    return n


@deal.post(lambda result: result is not None)
def double(n: int) -> int:
    """Twice n. It is pure, but its code does not say so, so it is never mutated."""
    return n * 2


@deal.has()
@deal.post(lambda result: len(result) > 0)
def greet(name: str) -> str:
    """A greeting. It claims to be pure but reads the environment, so the claim breaks and it is never mutated."""
    return os.environ.get("GREETING", "hello") + name


@dataclass(frozen=True)
class Tally:
    """A count, with a method and a property whose contracts the tests' calls check."""

    count: int

    @deal.has()
    @deal.ensure(lambda self, result: result == self.count + 1)
    def following(self) -> int:
        return self.count + 1

    @property
    @deal.has()
    @deal.post(lambda result: result >= 0)
    def magnitude(self) -> int:
        """No test reads it."""
        return -self.count if self.count < 0 else self.count


class Ledger:
    """Entries as they were given. Its constructor does not say what they are, so no ledger can be generated."""

    def __init__(self, entries):
        self.entries = tuple(entries)


@deal.has()
@deal.post(lambda result: result >= 0)
def total(ledger: Ledger) -> int:
    return sum(ledger.entries)
'''
TESTS = '''from zigdag import verifies
from calc.maths import Ledger, Tally, add, size, subtract, total


@verifies("calc.maths#sum")
def test_add():
    assert add(1, 2) == 3


@verifies("calc.maths#difference")
def test_subtract_gives_a_number():
    assert subtract(3, 1) is not None


def test_size():
    assert size(-2) == 2


def test_tally():
    assert Tally(2).following() == 3


def test_total():
    assert total(Ledger([4, 5])) == 9
'''
LOG = "design/log.jsonl"
WEAK_TEST = "tests.test_calc::test_subtract_gives_a_number"


def build(tmp_path: Path, process: str | None = None) -> Path:
    files = {"zigdag.toml": SETTINGS, "pyproject.toml": PYPROJECT, "design/customer.yaml": CUSTOMER,
             "design/functional.yaml": FUNCTIONAL, "src/calc/__init__.py": '"""Calc."""\n',
             "src/calc/maths.py": MATHS, "tests/test_calc.py": TESTS,
             **({"design/process.yaml": process} if process else {})}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def mutated_project(tmp_path: Path, process: str | None = None):
    root = build(tmp_path, process)
    main(["--project", str(root), "test"])
    return root, run(root)


def fates(analysis, function: str) -> set[MutantFate]:
    return {m.fate for m in analysis.code.observed.mutants if str(m.at) == f"calc.maths.{function}"}


@verifies("zigdag.watchers.python#mutate")
def test_a_change_counts_as_noticed_when_the_contract_or_a_test_that_runs_it_fails(tmp_path):
    _, a = mutated_project(tmp_path)
    assert fates(a, "add") == {MutantFate.KILLED}  # its contract misses it, but its test does not
    assert fates(a, "times") == {MutantFate.KILLED}  # its contract notices on its own
    assert fates(a, "subtract") == {MutantFate.SURVIVED} and fates(a, "negate") == {MutantFate.SURVIVED}
    killed = next(m for m in a.code.observed.mutants if str(m.at) == "calc.maths.add")
    assert killed.summary == "`return a + b` became `return a - b`"
    assert killed.detail == "tests.test_calc::test_add failed"
    survivor = next(m for m in a.code.observed.mutants if str(m.at) == "calc.maths.subtract")
    assert survivor.unnoticed_by == (WEAK_TEST,)
    assert all("@deal" not in m.edit for m in a.code.observed.mutants)  # the contract itself is never edited


@verifies("zigdag.core.analysis.checks#weak-contracts", "zigdag.core.analysis.checks#unmutated")
def test_a_change_nothing_notices_is_asked_about_and_takes_the_evidence_that_missed_it(tmp_path):
    _, a = mutated_project(tmp_path)
    asked = found(a, "mutation", Result.QUESTION)
    assert any("nothing notices when `return a - b` became `return a + b` in calc.maths.subtract: given a=" in s
               and "yet its contract holds for both, and the one test that runs it still passes" in s for s in asked)
    assert any("in calc.maths.negate: given n=" in s and "and no test runs it" in s for s in asked)
    assert not any("calc.maths.add" in s or "calc.maths.times" in s for s in asked)
    lost = found(a, "mutation", Result.TODO)
    assert any("the contract of calc.maths.subtract does not count as evidence for calc.maths#difference" in s
               for s in lost)
    assert any(f"{WEAK_TEST} does not count as evidence for calc.maths#difference" in s for s in lost)
    assert not any("calc.maths#sum" in s for s in lost)
    assert any("size marks a line not to be mutated" in s for s in found(a, "mutation"))


@verifies("zigdag.core.analysis.checks#weak-contracts")
def test_answering_every_unnoticed_change_gives_the_evidence_back(tmp_path):
    root, a = mutated_project(tmp_path)
    questions = [f for f in a.report.findings if f.rule == "mutation" and f.result is Result.QUESTION
                 and f.about == "calc.maths.subtract"]
    lines = [answered_question(Timestamp("2026-11-07T00:00:00Z"), Actor("reviewer"), q, Answer.ANSWERED,
                               "a difference that is a sum is checked elsewhere") for q in questions]
    (root / LOG).write_text("\n".join(lines) + "\n")
    again = run(root)
    assert not any(f.about == "calc.maths.subtract" for f in again.report.findings if f.rule == "mutation")
    assert not any("calc.maths#difference" in s for s in found(again, "mutation", Result.TODO))


@verifies("zigdag.watchers.python#search")
def test_a_change_no_input_shows_is_taken_as_equivalent_and_one_an_input_shows_comes_with_it(tmp_path):
    _, a = mutated_project(tmp_path)
    clamp = [m for m in a.code.observed.mutants if str(m.at) == "calc.maths.clamp"]
    equivalent = [m for m in clamp if m.fate is MutantFate.EQUIVALENT]
    assert any(m.summary == "`if n < 0:` became `if n <= 0:`" for m in equivalent)
    shown = next(m for m in clamp if m.summary == "`return 0` became `return 1`")
    assert shown.fate is MutantFate.SURVIVED and shown.witness is not None
    assert shown.witness.written == "returns 0" and shown.witness.mutated == "returns 1"
    asked = found(a, "mutation", Result.QUESTION)
    assert not any("`if n <= 0:`" in s for s in asked)  # taken as equivalent: nothing to answer
    assert any("`return 0` became `return 1` in calc.maths.clamp: given n=" in s for s in asked)


@verifies("zigdag.watchers.python#mutate")
def test_only_a_function_declared_pure_that_zigdag_finds_pure_is_mutated(tmp_path):
    _, a = mutated_project(tmp_path)
    assert not fates(a, "double")  # pure, but not declared so: running its mutants was never agreed to
    assert not fates(a, "greet")  # declared pure, but it reads the environment: its mutants could do what it can
    assert any("greet" in s for s in found(a, "declared-effects"))  # and the false declaration breaks
    assert not any("calc.maths.greet" in s or "calc.maths.double" in s for s in found(a, "mutation"))


@verifies("zigdag.core.analysis.checks#unmutated")
def test_a_function_left_out_on_purpose_is_listed_under_except(tmp_path):
    process = "mutation:\n  except:\n    - calc.maths.size  # abs is the whole function\n"
    _, a = mutated_project(tmp_path, process)
    assert not any("size" in s for s in found(a, "mutation"))
    assert not fates(a, "size")


@verifies("zigdag.core.analysis.checks#called-contracts")
def test_a_contract_no_inputs_are_generated_for_is_checked_on_the_calls_of_the_tests(tmp_path):
    _, a = mutated_project(tmp_path)
    cases = {str(c.at): c for c in a.code.observed.cases}
    method, unreadable = cases["calc.maths.Tally.following"], cases["calc.maths.total"]
    assert method.outcome is Outcome.SKIPPED and method.called_by == ("tests.test_calc::test_tally",)
    assert unreadable.outcome is Outcome.ERROR and unreadable.called_by == ("tests.test_calc::test_total",)
    asked = found(a, "contracts", Result.QUESTION)
    assert not any("following" in s or "total" in s for s in asked)  # the tests' calls checked them
    assert any("calc.maths.Tally.magnitude has a contract that was not run on generated inputs, and no test calls "
               "it" in s for s in asked)
    for function, test in (("Tally.following", "test_tally"), ("total", "test_total")):  # judged by the tests alone
        assert f"tests.test_calc::{test} failed" in {m.detail for m in a.code.observed.mutants
                                                       if str(m.at) == f"calc.maths.{function}"}


CARRIED = "from the last run"


def _marked(root: Path) -> None:
    """Every mutant the last run recorded, marked, so that one carried over can be told from one made again."""
    observed = root / ".zigdag/observed.json"
    seen = json.loads(observed.read_text())
    for m in seen["mutants"]:
        m["detail"] = CARRIED
    observed.write_text(json.dumps(seen))


def _carried(root: Path) -> tuple[set[str], set[str]]:
    """The functions whose mutants were carried over, and those whose mutants were made again."""
    main(["--project", str(root), "test"])
    mutants = run(root).code.observed.mutants
    return {str(m.at) for m in mutants if m.detail == CARRIED}, {str(m.at) for m in mutants if m.detail != CARRIED}


@verifies("zigdag.watchers.python#carry")
def test_mutants_are_made_again_only_when_the_function_or_the_tests_that_run_it_change(tmp_path):
    root, _ = mutated_project(tmp_path)
    maths = root / "src/calc/maths.py"
    maths.write_text(maths.read_text().replace("return a * b", "return b * a"))
    _marked(root)
    carried, made = _carried(root)
    assert "calc.maths.times" in made and "calc.maths.times" not in carried  # its own source changed
    assert {"calc.maths.add", "calc.maths.subtract", "calc.maths.negate", "calc.maths.clamp"} <= carried
    assert not carried & made
    tests = root / "tests/test_calc.py"
    tests.write_text(tests.read_text() + "\n# the tests changed\n")
    _marked(root)
    carried, made = _carried(root)
    assert {"calc.maths.add", "calc.maths.subtract", "calc.maths.Tally.following"} <= made  # the tests that ran them
    assert {"calc.maths.negate", "calc.maths.clamp", "calc.maths.times"} <= carried  # no test runs them


# ---- the search itself, on two versions of one function -----------------------------------------------------------


def _searched(contracted, written, changed) -> search.Searched:
    return search.search(contracted, written, None, functools.partial(_in_place, written, changed), PATHS, SECONDS)


@verifies("zigdag.watchers.python#search")
def test_the_search_finds_no_input_when_the_change_makes_no_difference():
    def written(n: int) -> int:
        return n if n > 0 else 0

    def changed(n: int) -> int:
        return n if n >= 0 else 0

    assert _searched(deal.post(lambda result: result >= 0)(written), written, changed).verdict is search.Verdict.SAME


@verifies("zigdag.watchers.python#search")
def test_the_search_finds_an_input_the_two_versions_differ_on():
    def written(n: int) -> int:
        return n + 1

    def changed(n: int) -> int:
        return n + 2

    found_ = _searched(deal.post(lambda result: result is not None)(written), written, changed)
    assert found_.verdict is search.Verdict.DIFFERENT
    n = int(found_.witness.input.removeprefix("n="))
    assert found_.witness.written == f"returns {n + 1}" and found_.witness.mutated == f"returns {n + 2}"


@verifies("zigdag.watchers.python#search")
def test_a_change_that_fails_the_contract_on_some_input_is_noticed_by_the_contract():
    def written(n: int) -> int:
        return 8 if n == 7 else n

    def changed(n: int) -> int:
        return 8 if n == 8 else n  # 7 now comes back as 7, which the contract forbids

    found_ = _searched(deal.post(lambda result: result != 7)(written), written, changed)
    assert found_.verdict is search.Verdict.CONTRACT_FAILS and found_.witness.input == "n=7"


@verifies("zigdag.watchers.python#search")
def test_the_search_leaves_out_inputs_the_preconditions_reject():
    def written(n: int) -> int:
        return abs(n)

    def changed(n: int) -> int:
        return n  # the same as abs for every n the precondition accepts

    contracted = deal.pre(lambda n: n >= 0)(written)
    assert _searched(contracted, written, changed).verdict is search.Verdict.SAME
