"""TypeScript tests as evidence, as vitest runs them: which tests verify what, how they are run, and their latest
results.

A test says which statements it verifies in its name:

    it("holds a line it is given verifies(shop.cart#hold)", () => { ... });

A test is named by its file and by the names of the groups it is in, as vitest's own report names it:
web/src/cart.test.ts::the cart > holds a line it is given verifies(shop.cart#hold).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator

import deal
from tree_sitter import Node

from zigdag.adapters.typescript.scan import Parsed
from zigdag.core.code import Link, Outcome, Qualified, Test, TestId
from zigdag.core.findings import RecordPath, Span, digest_of
from zigdag.core.measures import Column, Line
from zigdag.core.record.model import EvidenceKind
from zigdag.core.texts import Content, FileText, Written

ENCODING = "utf-8"
GROUPS = frozenset({"describe", "suite"})
TESTS = frozenset({"it", "test"})
BENCHMARKS = frozenset({"bench"})
PROPERTY_CALLS = ("fc.assert", "fc.property")  # fast-check: a test that runs its body on generated inputs
SEPARATOR = " > "  # how vitest joins a test's groups and its name
_VERIFIES = re.compile(r"verifies\(([^)]*)\)")
# What a name written for several cases stands for until it runs: %i, %s, $name. Each case's own name fills it in.
_FILLED = re.compile(r"%[a-zA-Z%#]|\$[A-Za-z_][\w.]*")
_RANK = {Outcome.PASSED: 0, Outcome.SKIPPED: 1, Outcome.ERROR: 2, Outcome.FAILED: 3}


def _text(node: Node | None) -> str:
    return node.text.decode(ENCODING) if node is not None and node.text is not None else ""


def _called(node: Node) -> str:
    """The first name of what a call calls, through what is called on it and what it is called with: `it` for
    it(...), it.skip(...), it.each([...])(...)."""
    function = node.child_by_field_name("function")
    while function is not None and function.type in ("member_expression", "call_expression"):
        function = function.child_by_field_name("object") or function.child_by_field_name("function")
    return _text(function)


def _title(node: Node) -> str | None:
    """The name a test or a group is given: its first argument, when that is a plain text."""
    arguments = node.child_by_field_name("arguments")
    first = arguments.named_children[0] if arguments is not None and arguments.named_children else None
    if first is None or first.type not in ("string", "template_string"):
        return None
    if any(part.type == "template_substitution" for part in first.named_children):
        return None
    return "".join(_text(part) for part in first.named_children if part.type in ("string_fragment", "escape_sequence")) \
        or _text(first)[1:-1]


def _calls(node: Node, groups: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str, Node]]:
    """Each test a piece of code declares, with the groups it is in, what declares it, and the call."""
    for child in node.named_children:
        if child.type != "call_expression":
            yield from _calls(child, groups)
            continue
        called, title = _called(child), _title(child)
        if title is not None and called in GROUPS:
            yield from _calls(child, (*groups, title))
        elif title is not None and called in TESTS | BENCHMARKS:
            yield (*groups, title), called, child
        else:
            yield from _calls(child, groups)


def _kind(called: str, call: Node) -> EvidenceKind:
    if called in BENCHMARKS:
        return EvidenceKind.BENCHMARK
    return EvidenceKind.PROPERTY_TEST if any(known in _text(call) for known in PROPERTY_CALLS) else EvidenceKind.UNIT_TEST


@deal.ensure(lambda parsed, imports, result: all(t.id.startswith(f"{parsed.path}::") for t in result))
def read_tests(parsed: Parsed, imports: Iterable[Qualified]) -> tuple[Test, ...]:
    """Every test a test file declares, each with what its name says it verifies. A test whose name is worked out,
    not written, has no name to know it by, and is left out."""
    imported = tuple(sorted(set(imports)))
    found = []
    for chain, called, call in _calls(parsed.root):
        row, column = call.start_point
        span = Span(parsed.path, Line(row + 1), Column(column + 1))
        links = tuple(Link(Written(target.strip()), span) for written in _VERIFIES.findall(chain[-1])
                      for target in written.split(",") if target.strip())
        found.append(Test(TestId(f"{parsed.path}::{SEPARATOR.join(chain)}"), links, _kind(called, call), imported,
                          span, source=digest_of(Content(_text(call)))))
    return tuple(found)


def name_pattern(name: str) -> re.Pattern[str]:
    """What a test's name looks like once it has run: as written, with whatever stood for a case filled in."""
    return re.compile(".*".join(re.escape(part) for part in _FILLED.split(name)))


def _file_meant(written: str, files: Iterable[RecordPath]) -> RecordPath | None:
    """The test file a report means: vitest names a file from the folder it ran in."""
    ending = [path for path in files if path == written or path.endswith(f"/{written}")]
    return max(ending, key=len) if ending else None


@deal.ensure(lambda report, tests, result: result is None or set(result) <= set(tests))
def read_report(report: FileText, tests: Iterable[TestId]) -> dict[TestId, Outcome] | None:
    """Each test's latest result, from the JUnit XML report vitest writes: a test case's class name is its file, and
    its name is its groups and its own name. A test written for several cases ran once for each, and the worst of
    their results is its own. None when the report cannot be read."""
    try:
        root = ET.fromstring(report)
    except ET.ParseError:
        return None
    by_file: dict[RecordPath, list[tuple[re.Pattern[str], TestId]]] = {}
    for test in tests:
        path, _, name = test.partition("::")
        by_file.setdefault(RecordPath(path), []).append((name_pattern(name), test))
    results: dict[TestId, Outcome] = {}
    for case in root.iter("testcase"):
        path = _file_meant(case.get("classname", ""), by_file)
        outcome = next((result for child, result in (("failure", Outcome.FAILED), ("error", Outcome.ERROR),
                                                     ("skipped", Outcome.SKIPPED)) if case.find(child) is not None),
                       Outcome.PASSED)
        for pattern, test in by_file.get(path, ()) if path is not None else ():
            if pattern.fullmatch(case.get("name", "")) is not None:
                if test not in results or _RANK[outcome] > _RANK[results[test]]:
                    results[test] = outcome
    return results
