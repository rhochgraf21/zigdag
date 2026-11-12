"""Terraform tests as evidence (`terraform test`): which runs verify what, which of them only plan, how they are
run, and their latest results.

A run says which statements it verifies in a comment, inside it or directly above it:

    # verifies: shop.receipts#keep
    run "receipts_are_private" {
      command = plan
      ...
    }

Terraform applies a run unless the run says `command = plan`, and no option of `terraform test` makes every run plan
only. So unless a project allows applying, a run that does not say so breaks, and its file is left out of the run:
nothing real is created by an oversight.
"""

from __future__ import annotations

import enum
import posixpath
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping

import deal

from zigdag.adapters.terraform.source import Block, BlockKind, blocks
from zigdag.core.code import Link, Outcome, Qualified, Test, TestId
from zigdag.core.findings import Digest, RecordPath, Span, digest_of
from zigdag.core.measures import Column
from zigdag.core.names import Argument
from zigdag.core.record.model import EvidenceKind
from zigdag.core.texts import Content, FileText, Written

SUFFIX = ".tftest.hcl"
_VERIFIES = re.compile(r"verifies:\s*(.+)$")
_COMMAND = re.compile(r"command\s*=\s*(\w+)")
_TEST, _JUNIT, _FILTER, _CHANGE_INTO = "test", "-junit-xml=", "-filter=", "-chdir="
_RANK = {Outcome.PASSED: 0, Outcome.SKIPPED: 1, Outcome.ERROR: 2, Outcome.FAILED: 3}


class Mode(enum.Enum):
    """What a project lets its Terraform tests do, as `test` in [adapters.terraform] says."""

    PLAN = "plan"  # every run only plans: nothing is created; what zigdag assumes
    APPLY = "apply"  # runs may apply, to an emulator or to a real account, as the project has set its providers up


def _runs(text: FileText) -> tuple[Block, ...]:
    return tuple(b for b in blocks(text) if b.kind is BlockKind.RUN)


@deal.pure
def plans_only(run: Block) -> bool:
    """Whether a run says `command = plan`. One that says nothing applies, as Terraform has it."""
    commands = [found.group(1) for line in run.own if (found := _COMMAND.match(line)) is not None]
    return commands == [Mode.PLAN.value]


@deal.ensure(lambda path, run, result: result.endswith(f"::{run.name}") and result.startswith(path))
def test_id(path: RecordPath, run: Block) -> TestId:
    return TestId(f"{path}::{run.name}")


def _links(path: RecordPath, run: Block) -> tuple[Link, ...]:
    return tuple(Link(Written(target.strip()), Span(path, line, Column(1)))
                 for line, comment in run.comments if (found := _VERIFIES.match(comment)) is not None
                 for target in found.group(1).split(",") if target.strip())


def _written(text: FileText, run: Block) -> Digest:
    """A digest of a run as it is written: every line of it, with the blocks inside it, where its assertions are,
    and its comments, where what it verifies is said."""
    lines = text.splitlines()[run.line - 1:run.line - 1 + run.size]
    return digest_of(*(Content(line) for line in (*lines, *(comment for _, comment in run.comments))))


@deal.ensure(lambda files, units, result: all(t.id.partition("::")[0] in files for t in result))
def read_tests(files: Mapping[RecordPath, FileText], units: Iterable[Qualified]) -> tuple[Test, ...]:
    """Every run of every test file. A test of a module can run any of what the module deploys, so each run counts
    as importing every unit given."""
    imports = tuple(sorted(units))
    return tuple(Test(test_id(path, run), _links(path, run), EvidenceKind.UNIT_TEST, imports,
                      Span(path, run.line, Column(1)), source=_written(text, run))
                 for path, text in sorted(files.items()) for run in _runs(text))


@deal.ensure(lambda files, mode, result: mode is Mode.PLAN or not result)
def applying(files: Mapping[RecordPath, FileText], mode: Mode) -> tuple[tuple[RecordPath, Block], ...]:
    """Each run that would apply although the project lets its tests only plan."""
    if mode is Mode.APPLY:
        return ()
    return tuple((path, run) for path, text in sorted(files.items()) for run in _runs(text) if not plans_only(run))


@deal.ensure(lambda files, mode, result: set(result) <= set(files))
def runnable(files: Mapping[RecordPath, FileText], mode: Mode) -> tuple[RecordPath, ...]:
    """The test files `zigdag test` runs: every one, less those with a run that would apply when it may not."""
    left_out = {path for path, _ in applying(files, mode)}
    return tuple(path for path in sorted(files) if path not in left_out)


@deal.pre(lambda start, root, files, report: bool(files))
@deal.ensure(lambda start, root, files, report, result: _TEST in result and len(
    [a for a in result if a.startswith(_FILTER)]) == len(files))
def command(start: tuple[Argument, ...], root: RecordPath, files: Iterable[RecordPath],
            report: RecordPath) -> tuple[Argument, ...]:
    """How the test files given are run, from the project's root: Terraform changes into the root module's folder,
    so each file and the report are named from there."""
    inside = root or "."
    return (*start, Argument(f"{_CHANGE_INTO}{inside}"), Argument(_TEST),
            Argument(f"{_JUNIT}{posixpath.relpath(report, inside)}"),
            *(Argument(f"{_FILTER}{posixpath.relpath(path, inside)}") for path in sorted(files)))


def _file_meant(written: str, files: Iterable[RecordPath]) -> RecordPath | None:
    """The test file a report means: it names a file from the root module's folder, where Terraform ran."""
    alike = [path for path in sorted(files) if path == written or path.endswith(f"/{written}")]
    return alike[0] if len(alike) == 1 else None


@deal.ensure(lambda report, files, result: result is None or all(t.partition("::")[0] in files for t in result))
def read_report(report: FileText, files: Iterable[RecordPath]) -> dict[TestId, Outcome] | None:
    """Each run's latest result, from the JUnit XML report `terraform test -junit-xml` writes: a test case is a run,
    and its class name is its file. None when the report cannot be read; a case of a file that is no test file here
    is left out."""
    known = tuple(files)
    try:
        root = ET.fromstring(report)
    except ET.ParseError:
        return None
    results: dict[TestId, Outcome] = {}
    for suite in root.iter("testsuite"):
        for case in suite.iter("testcase"):
            path = _file_meant(case.get("classname") or suite.get("name") or "", known)
            if path is None:
                continue
            outcome = next((result for child, result in (("failure", Outcome.FAILED), ("error", Outcome.ERROR),
                                                         ("skipped", Outcome.SKIPPED)) if case.find(child) is not None),
                           Outcome.PASSED)
            test = TestId(f"{path}::{case.get('name', '')}")
            if test not in results or _RANK[outcome] > _RANK[results[test]]:
                results[test] = outcome
    return results
