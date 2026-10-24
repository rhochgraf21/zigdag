from __future__ import annotations

from arch import realize, realizes
from arch.check import check
from arch.realize.evidence import parse_junit
from arch.realize.facts import Roots, Snapshot, SourcePath, Verdict, VcsLog
from arch.realize.history import History, parse_log
from arch.view.context import context
from arch.view.diagram import Observed, observed_matrix
from tests.conftest import NEED, component, graph

LOG = VcsLog("""commit c3
1\t0\tsrc/s/a.py
2\t1\tsrc/s/b.py

commit c2
1\t1\tsrc/s/{old => a}.py
1\t0\tsrc/s/b.py

commit c1
5\t0\tsrc/s/a.py
3\t3\tsrc/s/b.py
""" + "commit big\n" + "".join(f"1\t1\tsrc/s/f{i}.py\n" for i in range(31)))


@realizes("arch.realize.history#AC1", "arch.realize.history#AC2")
def test_log_parsing_skips_mass_edits_and_follows_renames():
    events = parse_log(LOG)
    assert [e.commit for e in events] == ["c3", "c2", "c1"]  # "big" touches 31 files: left out
    assert events[1].paths == ("src/s/a.py", "src/s/b.py")
    assert parse_log(LOG) == parse_log(LOG)


G = graph({"needs/n.md": NEED, "components/s.md": component(serves="n"),
           "components/s/a.md": component(serves="n"), "components/s/b.md": component(serves="n"),
           "components/s/c.md": component(serves="n", uses="a")})
CODE = {"src/s/__init__.py": "", "src/s/a.py": "", "src/s/b.py": "import s.c\n", "src/s/c.py": "import s.a\n",
        "tests/test_s.py": "@realizes('s.a#AC1')\ndef test_a(): ...\n@realizes('s.b#AC1')\ndef test_b(): ...\n"}
JUNIT = """<testsuites><testsuite>
<testcase classname="tests.test_s" name="test_a[case1]"/>
<testcase classname="tests.test_s" name="test_b"><failure message="boom"/></testcase>
<testcase classname="tests.test_s" name="test_c"><skipped/></testcase>
</testsuite></testsuites>"""


def facts(log=LOG, reports=None):
    snap = Snapshot({SourcePath(k): v for k, v in CODE.items()}, Roots(("src",), ("tests",)), log,
                    reports or {SourcePath(".arch/evidence/junit.xml"): JUNIT})
    return realize.extract(snap)


def test_history_counts_churn_and_co_change():
    h = History.of(facts())
    assert h.churn["s.a"] == 3 and h.co_changes(["s.a"], ["s.b"]) == 3


@realizes("arch.realize.evidence#AC1", "arch.realize.evidence#AC2")
def test_junit_outcomes_and_missing_reports():
    results = {r.test: r.outcome for r in parse_junit(SourcePath("r.xml"), JUNIT)}
    assert results == {"tests.test_s.test_a": Verdict.PASSED, "tests.test_s.test_b": Verdict.FAILED,
                       "tests.test_s.test_c": Verdict.SKIPPED}
    assert parse_junit(SourcePath("r.xml"), "not xml") == ()
    assert not [f for f in check(G, facts(reports={SourcePath("x.xml"): "<testsuites/>"})).findings if f.rule == "C010"]


@realizes("arch.check.conformance#AC9")
def test_failing_linked_tests_make_criteria_unmet():
    failing = [f for f in check(G, facts()).findings if f.rule == "C010"]
    assert [(f.subject, f.severity.value) for f in failing] == [("s.b", "error")]
    card = context(G, facts(), check(G, facts()), "s.a").to_markdown()
    assert "tests.test_s.test_a (passed)" in card


@realizes("arch.view.diagram#AC4")
def test_observed_matrix_marks_undeclared_imports_and_hidden_coupling():
    om = observed_matrix(G, "s", facts())
    assert om.cells[("s.c", "s.a")] is Observed.DECLARED
    assert om.cells[("s.b", "s.c")] is Observed.UNDECLARED_IMPORT
    assert om.cells[("s.a", "s.b")] is Observed.HIDDEN and om.together[("s.a", "s.b")] == 3
