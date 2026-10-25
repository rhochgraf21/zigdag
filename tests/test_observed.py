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
    report = check(G, facts())
    failing = [f for f in report.findings if f.rule == "C010"]
    assert [(f.subject, report.severity(f).value) for f in failing] == [("s.b", "error")]
    card = context(G, facts(), check(G, facts()), "s.a").to_markdown()
    assert "tests.test_s.test_a (passed)" in card


@realizes("arch.view.diagram#AC4")
def test_observed_matrix_marks_undeclared_imports_and_hidden_coupling():
    om = observed_matrix(G, "s", facts())
    assert om.cells[("s.c", "s.a")] is Observed.DECLARED
    assert om.cells[("s.b", "s.c")] is Observed.UNDECLARED_IMPORT
    assert om.cells[("s.a", "s.b")] is Observed.HIDDEN and om.together[("s.a", "s.b")] == 3


MUTMUT_META = """{"exit_code_by_key": {"s.a.x_add__mutmut_1": 1, "s.a.x_clamp__mutmut_1": 0,
 "s.a.x_clamp__mutmut_2": 0, "s.a.xǁBoxǁopen__mutmut_1": 1, "s.a.x_slow__mutmut_1": null,
 "s.a.x_odd__mutmut_1": 36}}"""


@realizes("arch.realize.evidence#AC4")
def test_mutmut_results_become_mutant_facts():
    from arch.realize.evidence import parse_mutmut
    from arch.realize.facts import MutantOutcome
    mutants = parse_mutmut(SourcePath("mutants/src/s/a.py.meta"), MUTMUT_META)
    got = {(m.symbol, m.outcome) for m in mutants}
    assert got == {("add", MutantOutcome.KILLED), ("clamp", MutantOutcome.SURVIVED), ("Box.open", MutantOutcome.KILLED),
                   ("slow", MutantOutcome.NOT_CHECKED), ("odd", MutantOutcome.INCONCLUSIVE)}
    assert {m.path for m in mutants} == {"src/s/a.py"}
    assert parse_mutmut(SourcePath("mutants/x.meta"), "not json") == ()


@realizes("arch.check.conformance#AC12")
def test_surviving_mutants_are_strict_at_higher_maturity():
    def run_at(status):
        design = graph({"needs/n.md": NEED, "components/s.md": component(serves="n"),
                        "components/s/a.md": component(serves="n", status=status)})
        snap = Snapshot({SourcePath("src/s/__init__.py"): "", SourcePath("src/s/a.py"): ""}, Roots(("src",), ()),
                        mutation_reports={SourcePath("mutants/src/s/a.py.meta"): MUTMUT_META})
        facts = realize.extract(snap)
        report = check(design, facts)
        return [(report.severity(f).value, f.message) for f in report.findings if f.rule == "C013"], context(design, facts, report, "s.a")
    for status, severity in (("specified", "info"), ("contracted", "info"), ("verified", "error")):  # evidence is claimed at verified
        found, card = run_at(status)
        assert found == [(severity, "2 of 4 mutants survived (in clamp)")]
    assert "**Mutation:** 2 of 4 mutants killed" in card.to_markdown()
