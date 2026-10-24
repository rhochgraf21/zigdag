"""Verification results from reports other tools produce.

Realizes arch.realize.evidence. Reads JUnit XML (pytest --junitxml, and most test runners). Test ids are
`<classname>.<name>` with parametrization stripped, which is the dotted id a design link on the test uses.
A missing report means "no evidence", never "failed".
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from arch.realize.facts import SourcePath, SourceText, Verdict, Evidence, Text


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
