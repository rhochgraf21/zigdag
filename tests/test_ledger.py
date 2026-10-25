from __future__ import annotations

from dataclasses import replace

from arch import realizes
from arch.check import check
from arch.check.engine import (
    PASSED, Finding, FindingKey, FindingRef, Kind, RuleId, Severity, Source, Station, Subject, parse_ref, ref_of,
    severity_of,
)
from arch.check.ledger import Answer, Ledger, Noticed, Response, accepting, digest_of, render_noticed, render_response
from arch.check.promotion import blockers
from arch.model.ids import Location, Text
from arch.model.schema import Status
from tests.conftest import NEED, component, graph

BROKEN = {"needs/n.md": NEED, "components/s.md": component(serves="n"), "components/s/a.md": component(uses="ghost", serves="n")}


def ledger_of(*entries) -> Ledger:
    files = {}
    for e in entries:
        files[e.path] = render_response(e) if isinstance(e, Response) else render_noticed(e)
    return Ledger.parse(files)


@realizes("arch.check.ledger#AC1", "arch.check#AC3")
def test_an_accepted_finding_is_reported_but_does_not_block():
    first = check(graph(BROKEN))
    assert first.blocking
    baseline = accepting(first.blocking, "baseline", Text("arch baseline"), Text("existed when arch was adopted"))
    again = check(graph(BROKEN), ledger=ledger_of(baseline))
    assert not again.blocking and all(again.is_answered(f) for f in first.blocking)


@realizes("arch.check.ledger#AC2")
def test_answers_to_findings_that_no_longer_occur_are_pointed_out():
    baseline = accepting(check(graph(BROKEN)).blocking, "baseline", Text("arch baseline"), Text("existing"))
    fixed = {**BROKEN, "components/s/a.md": component(serves="n")}
    gone = [f for f in check(graph(fixed), ledger=ledger_of(baseline)).findings if f.rule == "L001"]
    assert len(gone) == 1 and gone[0].severity is Severity.INFO


@realizes("arch.check.ledger#AC3", "arch.check.ledger#AC6")
def test_ledger_files_round_trip_and_an_answer_needs_a_reason():
    n = Noticed(Finding(Subject("s.a"), RuleId("claude"), FindingKey("weak-name"), Kind.IDEA, Text("Rename it."),
                        Text(""), None, Station.INTERFACE, source=Source.AGENT, evidence=Text("def f(x)")), "weak-name")
    r = Response("declined-weak-name", Answer.DECLINED, Text("robert"), Text("The name is the domain term."),
                 (n.finding.identity,))
    parsed = ledger_of(n, r)
    assert parsed.noticed[0].finding == replace(n.finding, location=Location(n.path))  # it knows its file
    assert parsed.responses == (r,)
    silent = Ledger.parse({r.path: render_response(replace(r, reason=Text("")))})
    assert any(f.rule == "L000" and f.severity is Severity.ERROR for f in silent.apply(check(graph(BROKEN)), graph(BROKEN)).findings)


@realizes("arch.check.engine#AC2", "arch.check.engine#AC4")
def test_severity_follows_the_station_the_kind_and_the_source():
    g = graph({"needs/n.md": NEED, "components/s.md": component(serves="n"),
               "components/s/d.md": component(serves="n", status="draft")})
    def sev(subject, station, kind=Kind.DEFECT, source=Source.RULE):
        return severity_of(Finding(Subject(subject), RuleId("X"), FindingKey("k"), kind, Text(""), Text(""),
                                   station=station, source=source), g)
    assert sev("s", Station.REQUIREMENTS) is Severity.ERROR  # specified: requirements are claimed done
    assert sev("s", Station.INTERFACE) is Severity.INFO  # not claimed yet
    assert sev("s.d", Station.REQUIREMENTS) is Severity.INFO and sev("s.d", Station.CODE) is Severity.ERROR  # code is always in force
    assert sev("s", Station.REQUIREMENTS, Kind.QUESTION) is Severity.WARNING
    assert sev("s", Station.REQUIREMENTS, source=Source.CRITIC) is Severity.WARNING  # only rules fail a check alone
    assert sev("s", Station.FORM, Kind.IDEA) is Severity.INFO
    assert PASSED[Status.VERIFIED] == frozenset(Station)


@realizes("arch.check.ledger#AC4")
def test_an_escape_answered_without_a_countermeasure_is_questioned():
    late = Noticed(Finding(Subject("s.a"), RuleId("robert"), FindingKey("adds-a-function"), Kind.DEFECT,
                           Text("AC3 adds a function"), Text(""), None, Station.REQUIREMENTS, source=Source.PERSON,
                           found_at=Station.REVIEW), "adds-a-function")
    fixed = Response("fixed-it", Answer.FIXED, Text("claude"), Text("Moved AC3 into its own component."), (late.finding.identity,))
    report = check(graph(BROKEN), ledger=ledger_of(late, fixed))
    assert late.finding.escaped and any(f.rule == "L002" and f.severity is Severity.WARNING for f in report.findings)
    with_cm = replace(fixed, countermeasure=Text("critic question: does a criterion add a function?"))
    assert not any(f.rule == "L002" for f in check(graph(BROKEN), ledger=ledger_of(late, with_cm)).findings)


@realizes("arch.check.ledger#AC5")
def test_a_finding_says_when_its_subject_has_changed_since():
    g = graph(BROKEN)
    n = Noticed(Finding(Subject("s.a"), RuleId("claude"), FindingKey("q"), Kind.QUESTION, Text("Is this right?"),
                        Text(""), None, Station.SOLUTION, source=Source.AGENT), "q", digest_of(g, Subject("s.a")))
    assert "changed since" not in next(f for f in check(g, ledger=ledger_of(n)).findings if f.rule == "claude").message
    edited = graph({**BROKEN, "components/s/a.md": component(uses="ghost", serves="n", hides="another secret")})
    assert "changed since" in next(f for f in check(edited, ledger=ledger_of(n)).findings if f.rule == "claude").message


@realizes("arch.check.promotion#AC1")
def test_a_status_rises_only_when_nothing_is_open_at_the_stations_it_claims():
    draft = {"needs/n.md": NEED, "components/s.md": component(serves="n"), "components/s/a.md": component(serves="n", status="draft", criteria=0)}
    before, after = graph(draft), graph({**draft, "components/s/a.md": component(serves="n", criteria=0)})
    open_ = blockers(before, after, check(after))
    assert [f.rule for f in open_] == ["S009"]  # specified claims requirements: it has no criteria
    assert blockers(before, before, check(before)) == ()


def test_finding_references_round_trip():
    identity = (RuleId("S107"), Subject("arch.x"), FindingKey("long:arch.x#AC2:criterion"))
    assert parse_ref(ref_of(identity)) == identity
    assert ref_of(identity) == FindingRef("S107@arch.x#long:arch.x#AC2:criterion")


@realizes("arch.integrate.catalog#AC7", "arch.check.promotion#AC1")
def test_raise_list_answer_and_promote_from_the_command_line(tmp_path, capsys):
    from arch.integrate.cli import main

    files = {"needs/n.md": NEED, "components/s.md": component(serves="n"),
             "components/s/a.md": component(serves="n", status="draft")}
    for path, text in files.items():
        (tmp_path / "design" / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "design" / path).write_text(text)
    run = lambda *argv: (main(["--project", str(tmp_path), *argv]), capsys.readouterr().out)  # noqa: E731
    code, out = run("raise", "question", "s.a", "Does AC1 add a function?", "--station", "requirements",
                    "--by", "claude", "--evidence", "do the thing")
    assert code == 0 and "noted question on s.a" in out
    ref = out.split(": ", 1)[1].splitlines()[0]
    code, out = run("set", "s.a", "status", "specified")
    assert code == 1 and "open finding" in out and ref in out  # a question at a newly claimed station blocks
    assert run("findings")[1].count(ref) == 1
    assert run("respond", "answered", "No: it pins down the one function.", ref, "--by", "robert")[0] == 0
    assert run("set", "s.a", "status", "specified")[0] == 0
    assert "taken up, by source: agent claude 0 of 1" in run("findings", "--all")[1]
