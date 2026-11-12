"""The TypeScript adapter: TypeScript source, package.json and tsconfig.json, read into the code model (DESIGN2 §5.2).

A file is a module, and a folder's index file is the folder. What a module exports is its public names. The source
is read as text by a parser, never by running the compiler, so a revision read from git is read the same way as the
files on disk.

Its tests are vitest's, and its diagnostics are what eslint and tsc report. Its watcher sees which modules ran in
each test, and no more of what the code does. Not read yet: what a security checker reports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import deal

from zigdag.adapters.tools import ToolOutput
from zigdag.adapters.typescript import apis, observed
from zigdag.adapters.typescript import tests as ts_tests
from zigdag.adapters.typescript.tools import diagnostics
from zigdag.adapters.typescript.modules import SUFFIXES, Resolver, declared_libraries, is_index, read_aliases, unit_path
from zigdag.adapters.typescript.scan import Facts, Project, Scanner, outline, parse
from zigdag.core.code import CodeModel, Diagnostic, Libraries, Observations, Outcome, Test, TestId, Unit, UnitKind
from zigdag.core.findings import Finding, RecordPath, Result, RuleName, Span, Subject, finding
from zigdag.core.kinds.registry import Part
from zigdag.core.measures import Column, Line, LineCount
from zigdag.core.names import TYPESCRIPT, CodePath, enclosing, is_inside
from zigdag.core.texts import FileText, Say, Written

ADAPTER_RULE = RuleName("typescript")
# What TypeScript code has that this adapter does not read yet.
CONTRACT_FORM = f"requires, ensures, from {apis.CONTRACT_LIBRARY}"  # how a TypeScript function states what it promises
# A TypeScript function's contract is read, and not yet run: no mutants of it are made.
NOT_READ_YET = frozenset({Part.SECURITY_DIAGNOSTICS, Part.MUTANTS})
_FOLDER_SIZE = LineCount(0)  # a folder with no index file has no lines of its own


@dataclass(frozen=True)
class TypeScriptFiles:
    """What the shell read for the TypeScript adapter."""

    sources: Mapping[RecordPath, FileText]  # every source file under the source roots, tests and declarations aside
    roots: tuple[RecordPath, ...]  # the source roots, such as "web"
    packages: Mapping[RecordPath, FileText] = field(default_factory=dict)  # each package.json
    configs: Mapping[RecordPath, FileText] = field(default_factory=dict)  # each tsconfig.json
    tests: Mapping[RecordPath, FileText] = field(default_factory=dict)  # every test file
    report: FileText | None = None  # what vitest wrote of its latest run, as JUnit XML
    report_path: RecordPath = RecordPath("")
    tools: tuple[ToolOutput, ...] = ()  # the linter and the type checker the shell ran
    seen: FileText | None = None  # what the watcher saw in the latest run of the tests
    contracts: CodePath | None = None  # the project's own module of requires and ensures, when it has one


def _first(path: RecordPath) -> Span:
    return Span(path, Line(1), Column(1))


def _units(files: TypeScriptFiles) -> dict[CodePath, Unit]:
    """Each source file as a module, and each folder on the way to one as a package. A folder's index file is the
    folder's own module; where a file and a folder's index would be the same module, it is the file, as it is for
    the compiler."""
    units: dict[CodePath, Unit] = {}
    for path, text in sorted(files.sources.items(), key=lambda item: (is_index(item[0]), item[0])):
        unit = unit_path(path)
        if unit in units and units[unit].kind is UnitKind.MODULE:
            continue
        kind = UnitKind.PACKAGE if is_index(path) else UnitKind.MODULE
        units[unit] = Unit(unit, TYPESCRIPT, kind, True, _first(path), LineCount(len(text.splitlines())))
    for path in sorted(files.sources):
        for folder in enclosing(Written(unit_path(path)))[1:]:
            if any(not root or is_inside(folder, Written(root)) for root in files.roots):
                units.setdefault(CodePath(folder), Unit(CodePath(folder), TYPESCRIPT, UnitKind.PACKAGE, True,
                                                        _first(path), _FOLDER_SIZE))
    return units


def _unread(path: RecordPath, why: str) -> Finding:
    return finding(Result.QUESTION, ADAPTER_RULE, Subject(path), _first(path), Say(why))


def _libraries(files: TypeScriptFiles) -> Libraries:
    """What the project's package.json files declare, together: a project of several packages declares each
    package's dependencies in its own file, and which file governs which import is not followed."""
    declared = [found for text in files.packages.values() if (found := declared_libraries(text)) is not None]
    return Libraries(frozenset().union(*declared) if declared else None, frozenset(), apis.STANDARD)


def _tests(files: TypeScriptFiles, project: Project) -> tuple[tuple[Test, ...], dict[TestId, Outcome], list[Finding]]:
    """The tests of the test files, their latest results, and what could not be read of them."""
    tests: list[Test] = []
    problems: list[Finding] = []
    for path, text in sorted(files.tests.items()):
        unit = unit_path(path)
        parsed = parse(path, unit, text)
        if parsed is None:
            problems.append(_unread(path, "could not be read (the parser found a syntax error), so the tests in "
                                          "it count as no evidence"))
            continue
        # A test file imports the code it tests, so it is read as one more module of the project, just for that.
        beside = Project({**project.outlines, unit: outline(parsed)}, {**project.files, unit: path},
                         project.resolver, project.contracts)
        tests += ts_tests.read_tests(parsed, Scanner(parsed, beside).imported())
    results = ts_tests.read_report(files.report, [t.id for t in tests]) if files.report is not None else {}
    if results is None:
        problems.append(_unread(files.report_path, "could not be read, so the tests in it count as no evidence"))
    return tuple(tests), results or {}, problems


def _watched(files: TypeScriptFiles, tests: tuple[Test, ...],
             results: Mapping[TestId, Outcome]) -> tuple[Observations | None, list[Finding]]:
    """What the watcher saw of the tests, and what is wrong with that. Tests that ran with no watcher attached are a
    thing to do: until it is, which code each test ran is a guess from what the test imports."""
    if files.seen is None:
        unattached = finding(Result.TODO, ADAPTER_RULE, Subject(observed.SEEN_FILE), None, Say(
            f"the TypeScript tests ran without zigdag's watcher, so which code each test ran is a guess from what "
            f"it imports. Attach it in the test section of the vitest config: {observed.ATTACHED_BY}"))
        return None, [unattached] if results else []
    seen = observed.read_seen(files.seen)
    if seen is None:
        return None, [_unread(observed.SEEN_FILE, "could not be read, so nothing seen while the tests ran was used")]
    return observed.observations(seen, [t.id for t in tests], {**files.sources, **files.tests}), []


def _diagnosed(files: TypeScriptFiles) -> tuple[list[Diagnostic], set[Part], list[Finding]]:
    """What the tools reported, which parts of the model that supplies, and each tool that could not report."""
    reported: list[Diagnostic] = []
    supplied: set[Part] = set()
    failures: list[Finding] = []
    for output in files.tools:
        found, failure = diagnostics(output, (*files.sources, *files.tests))  # eslint reads the tests too
        reported += found
        if failure is None:
            supplied.add(output.tool.diagnosis.part)
        else:
            failures.append(failure)
    return reported, supplied, failures


@deal.ensure(lambda files, result: all(u.adapter == TYPESCRIPT for u in result.units.values()))
@deal.ensure(lambda files, result: all(s.unit in result.units for s in result.symbols.values()))
def read_typescript(files: TypeScriptFiles) -> CodeModel:
    units = _units(files)
    own_file = {unit.path: unit.span.path for unit in units.values() if unit.span.path in files.sources
                and unit_path(unit.span.path) == unit.path}
    problems: list[Finding] = []
    aliases = []
    for path, text in sorted(files.configs.items()):
        read = read_aliases(path, text)
        if read is None:
            problems.append(_unread(path, "could not be read, so the import aliases it gives were not followed"))
        else:
            aliases.append(read)
    parsed = []
    for unit, path in sorted(own_file.items()):
        tree = parse(path, unit, files.sources[path])
        if tree is None:
            problems.append(_unread(path, "could not be read (the parser found a syntax error), so nothing in it "
                                          "was checked"))
        else:
            parsed.append(tree)
    stating = frozenset({apis.CONTRACT_LIBRARY, *((files.contracts,) if files.contracts else ())})
    project = Project({p.unit: outline(p) for p in parsed}, own_file, Resolver.of(files.sources, aliases), stating)
    facts: list[Facts] = [Scanner(p, project).scan() for p in parsed]
    tests, results, test_problems = _tests(files, project)
    reported, diagnosed, failures = _diagnosed(files)
    watched, watch_problems = _watched(files, tests, results)
    return CodeModel(
        units=units,
        symbols={s.qualified: s for f in facts for s in f.symbols},
        dependencies=tuple(d for f in facts for d in f.dependencies),
        calls=tuple(c for f in facts for c in f.calls),
        effects=tuple(e for f in facts for e in f.effects),
        unknowns=tuple(u for f in facts for u in f.unknowns),
        raises=tuple(r for f in facts for r in f.raises),
        accesses=tuple(a for f in facts for a in f.accesses),
        uses=tuple(u for f in facts for u in f.uses),
        planned_uses=tuple(u for f in facts for u in f.planned_uses),
        computations=tuple(c for f in facts for c in f.computations),
        tests=tests,
        results=results,
        observed=watched,
        reports_read=files.report is not None,
        diagnostics=tuple(reported),
        libraries={TYPESCRIPT: _libraries(files)},
        supplied=frozenset({Part.RECORD, Part.UNITS, Part.PUBLIC_NAMES, Part.DEPENDENCIES, Part.SYMBOLS,
                            Part.STRUCTURES, Part.CALLS_AND_EFFECTS, Part.CONTRACTS, Part.TESTS} | diagnosed
                           | ({Part.OBSERVATIONS} if watched is not None else set())),
        contract_forms={TYPESCRIPT: Say(CONTRACT_FORM)},
        unread={TYPESCRIPT: NOT_READ_YET},
        problems=(*problems, *test_problems, *failures, *watch_problems),
    )


__all__ = ["SUFFIXES", "TypeScriptFiles", "read_typescript"]
