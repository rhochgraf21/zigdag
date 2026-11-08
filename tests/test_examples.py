"""DESIGN2's worked examples are acceptance tests: the record of each must hold on its own."""

import pytest
from conftest import EXAMPLES, rules, says

from zigdag.cli import read_project
from zigdag.core.checks.run import check
from zigdag.core.findings import Result
from zigdag import verifies


@verifies("zigdag#check", "zigdag.core#find")
@pytest.mark.parametrize("name", ["mojo2verus", "shop"])
def test_the_worked_examples_hold(name):
    report = check(read_project(EXAMPLES / name))
    assert not report.breaks, says(report, Result.BREAKS)
    assert not report.of_result(Result.TODO), says(report, Result.TODO)
    assert rules(report, Result.QUESTION) == {"code-not-read"}


@verifies("zigdag.core#same-findings")
@pytest.mark.parametrize("name", ["mojo2verus", "shop"])
def test_checking_is_deterministic(name):
    files = read_project(EXAMPLES / name)
    assert check(files) == check(files)
