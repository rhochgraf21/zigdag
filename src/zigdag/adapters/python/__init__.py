"""The Python adapter: Python source, tests, test reports and pyproject.toml, read into the code model."""

from __future__ import annotations

import re
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass

import deal

from zigdag.adapters.python import apis
from zigdag.adapters.python.observed import Observed, Recording, current
from zigdag.adapters.python.scan import Facts, scan
from zigdag.adapters.python.tests import read_reports, read_tests
from zigdag.adapters.python.tools import diagnostics
from zigdag.adapters.tools import ToolOutput
from zigdag.core.codec import Unreadable
from zigdag.core.code import CodeModel, Diagnostic, Libraries, Unit, UnitKind
from zigdag.core.findings import Finding, RecordPath, Result, Span, digest_of, finding
from zigdag.core.kinds.registry import Part
from zigdag.core.settings import OBSERVED_FILE
from zigdag.core.names import AdapterName, CodePath
from zigdag.core.texts import FileText

PYTHON = AdapterName("python")
ADAPTER_RULE = "python"
CONTRACT_FORM = "@deal.post, @deal.ensure"  # how a Python function states what it promises


@dataclass(frozen=True)
class PythonFiles:
    """What the shell read for the Python adapter."""

    sources: Mapping[RecordPath, FileText]  # every .py file under the source roots
    roots: tuple[RecordPath, ...]  # the source roots, such as "src"
    vendor: tuple[RecordPath, ...]  # folders of vendored code, which is a library, not part of the design
    tests: Mapping[RecordPath, FileText]
    pyproject: FileText | None
    reports: Mapping[RecordPath, FileText]  # JUnit XML
    observed: FileText | None = None  # what the watcher saw in the latest watched run of the tests
    tools: tuple[ToolOutput, ...] = ()  # the linters and type checkers the shell ran, for the rules that need them


def _module_path(path: RecordPath, roots: tuple[str, ...]) -> tuple[list[str], bool] | None:
    """The dotted parts of a source file's module, and whether it is a package's own __init__."""
    for root in sorted(roots, key=len, reverse=True):
        prefix = f"{root.rstrip('/')}/" if root else ""
        if path.startswith(prefix):
            parts = path[len(prefix):].removesuffix(".py").split("/")
            init = parts[-1] == "__init__"
            return (parts[:-1] if init else parts), init
    return None


def _vendored(path: str, vendor: tuple[str, ...]) -> bool:
    return any(path == v.rstrip("/") or path.startswith(v.rstrip("/") + "/") for v in vendor)


def declared_libraries(pyproject: str | None) -> frozenset[str] | None:
    """The import names the project's runtime dependencies provide, or None when nothing can be read."""
    if pyproject is None:
        return None
    try:
        project = tomllib.loads(pyproject).get("project", {})
    except tomllib.TOMLDecodeError:
        return None
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements += extra
    names: set[str] = set()
    for requirement in requirements:
        match = re.match(r"[A-Za-z0-9._-]+", requirement)
        if not match:
            continue
        normal = match.group().lower().replace("-", "_")
        names |= {normal, normal.split(".")[0], *apis.DISTRIBUTION_IMPORTS.get(normal, ())}
    return frozenset(names)


@deal.pre(lambda files: not any("\0" in p for p in (*files.sources, *files.tests, *files.reports)))  # paths on disk
@deal.ensure(lambda files, result: all(s.unit in result.units for s in result.symbols.values()))
@deal.ensure(lambda files, result: all(u.adapter == PYTHON for u in result.units.values()))
def read_python(files: PythonFiles) -> CodeModel:
    units: dict[CodePath, Unit] = {}
    vendored: set[str] = set()
    facts: list[Facts] = []
    problems: list[Finding] = []
    for path, text in sorted(files.sources.items()):
        located = _module_path(path, files.roots)
        if located is None:
            continue
        parts, init = located
        dotted = ".".join(parts)
        if _vendored(path, files.vendor):
            vendor_root = next(v.rstrip("/") for v in files.vendor if path.startswith(v.rstrip("/") + "/"))
            inside = path[len(vendor_root) + 1:].split("/")[0].removesuffix(".py")
            vendored |= {inside, ".".join(_module_path(RecordPath(f"{vendor_root}/{inside}.py"), files.roots)[0])}
            continue
        for i in range(1, len(parts)):  # every folder on the way is a package, with or without __init__.py
            package = CodePath(".".join(parts[:i]))
            units.setdefault(package, Unit(package, PYTHON, UnitKind.PACKAGE,
                                           all(not p.startswith("_") for p in parts[:i]), Span(path, 1, 1), 0))
        if not parts:
            continue
        unit = CodePath(dotted)
        kind = UnitKind.PACKAGE if init else UnitKind.MODULE
        units[unit] = Unit(unit, PYTHON, kind, all(not p.startswith("_") for p in parts), Span(path, 1, 1),
                           len(text.splitlines()))
        found, problem = scan(unit, dotted if init else ".".join(parts[:-1]), path, text)
        if found is None:
            problems.append(finding(Result.QUESTION, ADAPTER_RULE, path, Span(path, 1, 1),
                                    f"could not be read ({problem}), so nothing in it was checked"))
        else:
            facts.append(found)
    tests, unreadable_tests = read_tests(files.tests)
    results, unreadable_reports = read_reports(files.reports)
    for path in (*unreadable_tests, *unreadable_reports):
        problems.append(finding(Result.QUESTION, ADAPTER_RULE, path, Span(path, 1, 1),
                                "could not be read, so the tests in it count as no evidence"))
    symbols = {s.qualified: s for f in facts for s in f.symbols}
    seen = _observed(files, units, problems)
    supplied = {Part.RECORD, Part.UNITS, Part.PUBLIC_NAMES, Part.DEPENDENCIES, Part.SYMBOLS, Part.STRUCTURES,
                Part.CALLS_AND_EFFECTS, Part.CONTRACTS, Part.MUTANTS, Part.TESTS}
    diagnosed: list[Diagnostic] = []
    for output in files.tools:
        reported, failure = diagnostics(output)
        diagnosed += reported
        if failure is None:
            supplied.add(output.tool.diagnosis.part)
        else:
            problems.append(failure)
    return CodeModel(
        units=units,
        symbols=symbols,
        dependencies=tuple(d for f in facts for d in f.dependencies) + (seen.dependencies if seen else ()),
        calls=tuple(c for f in facts for c in f.calls) + (seen.calls if seen else ()),
        effects=tuple(e for f in facts for e in f.effects) + (seen.effects if seen else ()),
        unknowns=tuple(u for f in facts for u in f.unknowns),
        raises=tuple(r for f in facts for r in f.raises),
        accesses=tuple(a for f in facts for a in f.accesses) + (seen.accesses if seen else ()),
        uses=tuple(u for f in facts for u in f.uses),
        planned_uses=tuple(u for f in facts for u in f.planned_uses),
        computations=tuple(c for f in facts for c in f.computations),
        tests=tests + tuple(t for f in facts for t in f.contracts),
        results=results,
        reports_read=bool(files.reports),
        observed=seen.observations if seen else None,
        diagnostics=tuple(diagnosed),
        resource_uses=tuple(u for f in facts for u in f.resource_uses),
        libraries={PYTHON: Libraries(declared_libraries(files.pyproject), frozenset(vendored),
                                     frozenset(sys.stdlib_module_names) | {"__future__"})},
        contract_forms={PYTHON: CONTRACT_FORM},
        supplied=frozenset(supplied | ({Part.OBSERVATIONS} if seen else set())),
        problems=tuple(problems),
    )


def _observed(files: PythonFiles, units: Mapping[CodePath, Unit], problems: list[Finding]) -> Observed | None:
    """What the latest watched run saw that is still current with the code."""
    if files.observed is None:
        return None
    recording = Recording.from_text(files.observed)
    if isinstance(recording, Unreadable):
        problems.append(finding(Result.QUESTION, ADAPTER_RULE, OBSERVED_FILE, Span(OBSERVED_FILE, 1, 1),
                                f"could not be read ({recording.say}), so nothing seen while the tests ran was used"))
        return None
    now = {path: digest_of(text) for path, text in {**files.sources, **files.tests}.items()}
    files_of = {unit: path for path, unit in CodeModel(units=units).files.items()}
    return current(recording, now, files_of)
