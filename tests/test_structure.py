from __future__ import annotations

from arch import realizes
from arch.check import check
from arch.check.engine import Severity
from tests.conftest import NEED, component, graph

BASE = {"needs/n.md": NEED, "components/s.md": component(serves="n")}
CONTRADICTION = "---\nkind: contradiction\nstatus: accepted\naffects: [s.a, s.b]\n---\nWe accept it.\n"


def findings(files):
    return {(f.rule, f.subject, f.severity) for f in check(graph({**BASE, **files})).findings}


@realizes("arch.check.structure#AC1")
def test_coupling_is_an_error_unless_recorded():
    coupled = {"components/s/a.md": component(uses="b", serves="n"), "components/s/b.md": component(uses="a", serves="n")}
    assert ("S005", "s", Severity.ERROR) in findings(coupled)
    assert ("S005", "s", Severity.WARNING) in findings({**coupled, "decisions/X01.md": CONTRADICTION})


@realizes("arch.check.structure#AC4")
def test_uses_must_stay_within_parent_allowance():
    files = {
        "components/s/a.md": component(serves="n"),
        "components/s/b.md": component(serves="n"),
        "components/s/a/x.md": component(uses="b"),  # a does not use b
    }
    assert ("S007", "s.a.x", Severity.ERROR) in findings(files)


def test_uses_must_be_visible():
    files = {
        "components/s/a.md": component(serves="n"),
        "components/s/a/hidden.md": component(),
        "components/s/b.md": component(uses="a.hidden", serves="n"),
    }
    assert ("S008", "s.b", Severity.ERROR) in findings(files)


@realizes("arch.check.structure#AC3", "arch.check#AC5")
def test_secret_severity_scales_with_maturity():
    for status, sev in (("draft", Severity.INFO), ("specified", Severity.WARNING), ("contracted", Severity.ERROR)):
        assert ("S006", "s.a", sev) in findings({"components/s/a.md": component(hides=None, status=status, serves="n")})


@realizes("arch.check.structure#AC2")
def test_span():
    kids = {f"components/s/c{i}.md": component(serves="n") for i in range(10)}
    assert ("S004", "s", Severity.WARNING) in findings(kids)


def test_dangling_and_untraced():
    got = findings({"components/s/a.md": component(uses="ghost")})
    assert ("S001", "s.a", Severity.ERROR) in got
    assert ("S002", "s.a", Severity.ERROR) in got
    assert ("S003", "n", Severity.ERROR) in got
