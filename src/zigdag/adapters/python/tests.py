"""Python tests as evidence: which tests verify what, what kind of evidence each is, and their latest results."""

from __future__ import annotations

import ast
import xml.etree.ElementTree as ET
from collections.abc import Mapping

from zigdag.adapters.python import apis
from zigdag.adapters.python.scan import Scanner
from zigdag.core.code import Link, Outcome, Qualified, Test
from zigdag.core.findings import RecordPath, Span
from zigdag.core.names import CodePath
from zigdag.core.record.model import EvidenceKind


def test_module(path: RecordPath) -> str:
    return path.removesuffix(".py").replace("/", ".")


def _kind(scanner: Scanner, node: ast.FunctionDef | ast.AsyncFunctionDef) -> EvidenceKind:
    names = {scanner.resolve(d.func if isinstance(d, ast.Call) else d) for d in node.decorator_list}
    calls = {scanner.resolve(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)}
    if apis.HYPOTHESIS_GIVEN in names or apis.DEAL_CASES in names | calls:
        return EvidenceKind.PROPERTY_TEST
    if any(a.arg == "benchmark" for a in node.args.args):
        return EvidenceKind.BENCHMARK
    return EvidenceKind.UNIT_TEST


def _links(scanner: Scanner, node: ast.FunctionDef | ast.AsyncFunctionDef, path: RecordPath) -> tuple[Link, ...]:
    out = []
    for d in node.decorator_list:
        if isinstance(d, ast.Call) and (scanner.resolve(d.func) or "").split(".")[-1] == "verifies":
            out += [Link(a.value, Span(path, a.lineno, a.col_offset + 1)) for a in d.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    return tuple(out)


def read_tests(files: Mapping[RecordPath, str]) -> tuple[tuple[Test, ...], tuple[RecordPath, ...]]:
    """Every test function, and the test files that could not be read."""
    tests: list[Test] = []
    unreadable: list[RecordPath] = []
    for path, text in sorted(files.items()):
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError:
            unreadable.append(path)
            continue
        module = test_module(path)
        scanner = Scanner(CodePath(module), module.rpartition(".")[0], path, tree, text)
        imports = tuple(sorted({Qualified(v) for v in scanner.names.values() if not v.startswith(module + ".")}))
        candidates: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
                candidates.append((node.name, node))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                candidates += [(f"{node.name}::{m.name}", m) for m in node.body
                               if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef) and m.name.startswith("test")]
        for name, node in candidates:
            tests.append(Test(f"{module}::{name}", _links(scanner, node, path), _kind(scanner, node), imports,
                              Span(path, node.lineno, node.col_offset + 1)))
    return tuple(tests), tuple(unreadable)


_RANK = {Outcome.PASSED: 0, Outcome.SKIPPED: 1, Outcome.ERROR: 2, Outcome.FAILED: 3}


def read_reports(reports: Mapping[RecordPath, str]) -> tuple[dict[str, Outcome], tuple[RecordPath, ...]]:
    """Test id -> its result, from JUnit XML reports; parametrised cases count as one, the worst result winning."""
    results: dict[str, Outcome] = {}
    unreadable: list[RecordPath] = []
    for path, text in sorted(reports.items()):
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            unreadable.append(path)
            continue
        for case in root.iter("testcase"):
            classname, name = case.get("classname", ""), case.get("name", "").split("[")[0]
            module, _, last = classname.rpartition(".")
            test = f"{module}::{last}::{name}" if last[:4] == "Test" else f"{classname}::{name}"
            outcome = Outcome.PASSED
            for child, result in (("failure", Outcome.FAILED), ("error", Outcome.ERROR),
                                  ("skipped", Outcome.SKIPPED)):
                if case.find(child) is not None:
                    outcome = result
                    break
            if test not in results or _RANK[outcome] > _RANK[results[test]]:
                results[test] = outcome
    return results, tuple(unreadable)
