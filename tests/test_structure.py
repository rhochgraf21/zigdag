from __future__ import annotations

from arch import realizes
from arch.check import check
from arch.check.engine import Severity
from tests.conftest import NEED, component, graph

BASE = {"needs/n.md": NEED, "components/s.md": component(serves="n")}


def findings(files):
    return {(f.rule, f.subject, f.severity) for f in check(graph({**BASE, **files})).findings}


COUPLED = {"components/s/a.md": component(uses="b", serves="n"), "components/s/b.md": component(uses="a", serves="n")}


@realizes("arch.check.structure#AC1")
def test_coupling_is_an_error_unless_the_parent_accepts_it():
    assert ("S005", "s", Severity.ERROR) in findings(COUPLED)
    accepted = findings({**COUPLED, "components/s.md": component(serves="n", accepts="a, b")})
    assert ("S005", "s", Severity.WARNING) in accepted
    assert ("S005", "s", Severity.ERROR) not in accepted


@realizes("arch.check.structure#AC5")
def test_stale_acceptance_is_reported():
    files = {
        "components/s.md": component(serves="n", accepts="a, b"),
        "components/s/a.md": component(serves="n"),
        "components/s/b.md": component(serves="n"),
    }
    stale = [f for f in check(graph({**BASE, **files})).findings if f.key.startswith("stale:")]
    assert [f.severity for f in stale] == [Severity.WARNING]


@realizes("arch.check.structure#AC6")
def test_decision_entries_need_chose_and_because():
    good = "## Decisions\n### Use X\n- Chose: X\n- Because: it is simplest\n"
    bad = "## Decisions\n### Use Y\nWe like Y.\n"
    assert not any(r == "S010" for r, _, _ in findings({"components/s/a.md": component(serves="n", body=good)}))
    assert ("S010", "s.a", Severity.WARNING) in findings({"components/s/a.md": component(serves="n", body=bad)})


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
