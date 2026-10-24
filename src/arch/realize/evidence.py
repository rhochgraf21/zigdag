"""Verification results from reports other tools produce.

Realizes arch.realize.evidence. Reads JUnit XML (pytest --junitxml, and most test runners) and mutmut's
per-file `.meta` results. Test ids are `<classname>.<name>` with parametrization stripped, which is the
dotted id a design link on the test uses. A missing report means "no evidence", never "failed".
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from arch.realize.facts import Evidence, Mutant, MutantOutcome, SourcePath, SourceText, SymbolName, Text, Verdict


def parse_junit(path: SourcePath, text: SourceText) -> tuple[Evidence, ...]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ()
    results = []
    for case in root.iter("testcase"):
        name = case.get("name", "").split("[", 1)[0]
        classname = case.get("classname", "")
        if not name:
            continue
        test = Text(f"{classname}.{name}" if classname else name)
        results.append(Evidence(test, _outcome(case), path))
    return tuple(results)


def _outcome(case: ET.Element) -> Verdict:
    tags = {child.tag for child in case}
    if "error" in tags:
        return Verdict.ERROR
    if "failure" in tags:
        return Verdict.FAILED
    if "skipped" in tags:
        return Verdict.SKIPPED
    return Verdict.PASSED


MUTMUT_DIR = "mutants"
_KILLED_CODES = frozenset({1})  # exit codes verified against mutmut 3.8; others are treated as inconclusive
_SURVIVED_CODES = frozenset({0})


def parse_mutmut(meta_path: SourcePath, text: SourceText) -> tuple[Mutant, ...]:
    """Mutants from one `mutants/<source>.meta` file; keys look like `pkg.mod.x_func__mutmut_3`."""
    source = SourcePath(meta_path.removeprefix(f"{MUTMUT_DIR}/").removesuffix(".meta"))
    try:
        codes = json.loads(text).get("exit_code_by_key", {})
    except (json.JSONDecodeError, AttributeError):
        return ()
    if not isinstance(codes, dict):
        return ()
    mutants = []
    for key, code in sorted(codes.items()):
        function = key.rsplit("__mutmut_", 1)[0].rsplit(".", 1)[-1]
        symbol = SymbolName(function.removeprefix("x").lstrip("_ǁ").replace("ǁ", "."))
        if code is None:
            outcome = MutantOutcome.NOT_CHECKED
        elif code in _KILLED_CODES:
            outcome = MutantOutcome.KILLED
        elif code in _SURVIVED_CODES:
            outcome = MutantOutcome.SURVIVED
        else:
            outcome = MutantOutcome.INCONCLUSIVE
        mutants.append(Mutant(source, symbol, outcome))
    return tuple(mutants)
