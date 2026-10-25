from __future__ import annotations

import json

from arch import realizes
from arch.check import check
from arch.check import critique as critic
from arch.check.engine import FindingKey, Subject
from arch.check.ledger import Answer, Ledger, Response, render_response
from arch.model.ids import ComponentId, Text
from arch.model.policy import Critique, Policy
from arch.model.schema import Kind as NodeKind
from arch.realize import extract
from arch.realize.facts import Roots, Snapshot, SourcePath
from tests.conftest import NEED, component, graph

CRITIQUED = "---\nkind: constraint\napplies_to: [s]\nrule:\n  critique: {required: true}\n---\nDesign text is critiqued.\n"
DESIGN = {"needs/n.md": NEED, "components/s.md": component(serves="n"),
          "components/s/a.md": component(serves="n"), "components/s/b.md": component(serves="n", uses="a"),
          "constraints/critiqued.md": CRITIQUED}


def answer(reviewed, findings=(), rubric=critic.RUBRIC_VERSION) -> critic.CriticAnswer:
    return critic.CriticAnswer.parse(critic.AnswerText(json.dumps(
        {"critic": "fresh-agent", "rubric": rubric, "reviewed": list(reviewed), "findings": list(findings)})))


@realizes("arch.check.critique#AC3", "arch.model.policy#AC5")
def test_nodes_under_a_critique_policy_wait_for_a_critic():
    assert Policy.parse({"critique": {"required": True}})[0].critique is Critique.REQUIRED
    waiting = {f.subject for f in check(graph(DESIGN)).findings if f.rule == "Q001"}
    assert waiting == {"s", "s.a", "s.b", "n", "critiqued"}  # the top level covers needs and constraints too
    plain = {k: v for k, v in DESIGN.items() if not k.startswith("constraints/")}
    assert not any(f.rule == "Q001" for f in check(graph(plain)).findings)


@realizes("arch.check.critique#AC4")
def test_a_critiqued_node_counts_until_its_text_changes():
    g = graph(DESIGN)
    stamp = Response("critiqued", Answer.ANSWERED, Text("fresh-agent"), Text("Judged with rubric 1: 0 findings."),
                     (critic.wanted(g, Subject("s.a")),))
    ledger = Ledger.parse({stamp.path: render_response(stamp)})
    q001 = {f.subject: check(g, ledger=ledger).is_answered(f) for f in check(g, ledger=ledger).findings if f.rule == "Q001"}
    assert q001["s.a"] and not q001["s.b"]
    edited = graph({**DESIGN, "components/s/a.md": component(serves="n", hides="another secret")})
    report = check(edited, ledger=ledger)
    assert not any(report.is_answered(f) for f in report.findings if f.rule == "Q001" and f.subject == "s.a")


@realizes("arch.check.critique#AC1", "arch.check.critique#AC2")
def test_only_findings_that_quote_the_text_and_ask_a_rubric_question_are_kept():
    g = graph(DESIGN)
    good = {"subject": "s.a", "question": "hides-no-decision", "quote": "hides: a secret",
            "message": "It names no decision.", "hint": "Say which decision it keeps from the others."}
    verdict = critic.judge(answer(["s.a", "ghost"], [
        good,
        {**good, "quote": "hides: implementation details"},  # not in the text
        {**good, "question": "need-names-solution"},  # a question about needs, asked of a component
        {**good, "question": "made-up"},
        {**good, "message": " "},
    ]), g)
    assert [f.evidence for f in verdict.findings] == ["hides: a secret"] and verdict.reviewed == ("s.a",)
    assert len(verdict.refused) == 5  # the unknown subject, and four bad findings
    assert critic.judge(answer(["s.a"], rubric="0"), g).refused  # an answer for another rubric is refused whole


@realizes("arch.check.critique#AC5")
def test_a_calibration_answer_is_scored_against_the_rubric_examples():
    request = json.loads(critic.calibration_request().to_json())
    assert not any("flags" in q or "passes" in q for q in request["questions"])  # blind: the examples are the test
    subjects = [s["subject"] for s in request["subjects"]]
    flags = [{"subject": s, "question": s.split(":")[1], "quote": "x", "message": "flagged"}
             for s in subjects if s.endswith(":flags")]
    perfect = critic.score(answer(subjects, flags))
    assert all(a.right == a.asked == 2 for a in perfect) and len(perfect) == len(critic.RUBRIC)
    lazy = critic.score(answer(subjects))  # flags nothing
    assert all(a.right == 1 for a in lazy)
    assert answer(subjects).purpose is critic.Purpose.CALIBRATION


@realizes("arch.check.critique#AC6")
def test_a_request_gives_only_the_text_and_its_near_context():
    g = graph(DESIGN)
    (piece,) = critic.request(g, (Subject("s.b"),)).pieces
    context = dict(piece.context)
    assert piece.text == g.design.sources["components/s/b.md"]
    assert context["parent solution"] == g[ComponentId("s")].solution and "s.a: Do the thing" in context["siblings"]
    doc = json.loads(critic.request(g, (Subject("s.b"),)).to_json())
    assert {q["part"] for q in doc["questions"]} == {"requirement", "criterion", "solution", "decision", "interface"}


@realizes("arch.check.critique#AC7")
def test_every_rubric_question_states_its_principle_and_examples():
    assert len({q.id for q in critic.RUBRIC}) == len(critic.RUBRIC)
    for q in critic.RUBRIC:
        assert q.ask.endswith("?") or "?" in q.ask, q.id
        assert q.because and q.flags and q.passes and q.flags != q.passes, q.id


@realizes("arch.check.critique#AC4", "arch.integrate.catalog#AC7")
def test_request_record_and_recritique_from_the_command_line(tmp_path, capsys):
    from arch.integrate.cli import main

    for path, text in DESIGN.items():
        (tmp_path / "design" / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "design" / path).write_text(text)
    run = lambda *argv: (main(["--project", str(tmp_path), *argv]), capsys.readouterr().out)  # noqa: E731
    assert "5 nodes wait for an independent critic" in run("critique")[1]
    request = json.loads(run("critique", "s", "--request")[1])
    assert {s["subject"] for s in request["subjects"]} == {"s", "s.a", "s.b"}
    reply = {"critic": "fresh-agent", "rubric": request["rubric"], "reviewed": ["s", "s.a", "s.b"],
             "findings": [{"subject": "s.a", "question": "hides-no-decision", "quote": "hides: a secret",
                           "message": "It names no decision.", "hint": "Name it."}]}
    (tmp_path / "answer.json").write_text(json.dumps(reply))
    code, out = run("critique", "--record", str(tmp_path / "answer.json"))
    assert code == 0 and "reviewed 3: 1 findings recorded" in out
    assert "2 nodes wait" in run("critique")[1]  # the need and the constraint
    assert "hides-no-decision@s.a" in run("findings")[1]
    assert "noticed before" in run("critique", "--record", str(tmp_path / "answer.json"))[1]  # not stored twice
    stamps = sorted((tmp_path / "design/responses").glob("critiqued-by-*.md"))
    assert len(stamps) == 1  # the second critique of the same nodes replaced the first
    ref = next(line.split()[2] for line in run("findings")[1].splitlines() if "hides-no-decision" in line)
    run("respond", "declined", "The secret is named well enough.", ref, "--by", "robert")
    assert "noticed before" in run("critique", "--record", str(tmp_path / "answer.json"))[1]  # a settled one stays settled
    run("respond", "fixed", "Named the decision.", ref, "--by", "robert")
    (tmp_path / "design/responses").joinpath("declined-s-a-s-a-hides-no-decision.md").unlink(missing_ok=True)
    assert "1 findings recorded" in run("critique", "--record", str(tmp_path / "answer.json"))[1]  # the fix did not hold


def stamped(g, subject, version) -> Ledger:
    """A ledger saying a critic judged `subject` at its current text under rubric `version`."""
    rule, _, current = critic.wanted(g, subject)
    identity = (rule, subject, FindingKey(f"{current.rpartition(':v')[0]}:v{version}"))
    stamp = Response("critiqued", Answer.ANSWERED, Text("fresh-agent"), Text("Judged."), (identity,))
    return Ledger.parse({stamp.path: render_response(stamp)})


@realizes("arch.check.critique#AC9", "arch.check.critique#AC10")
def test_a_node_judged_under_an_older_rubric_is_asked_only_the_new_questions():
    g = graph(DESIGN)
    newer = critic.asked_since(NodeKind.COMPONENT, critic.Version(1))
    assert newer and all(critic._BY_ID[q].since == 2 for q in newer)
    assert not critic.asked_since(NodeKind.NEED, critic.Version(1))  # needs got no new questions: not judged again
    ledger = stamped(g, Subject("s.a"), 1)
    asked = critic.still_to_ask(g, ledger)
    assert asked == {Subject("s.a"): newer}
    doc = json.loads(critic.request(g, (Subject("s.a"),), asked=asked).to_json())
    assert {q["id"] for q in doc["questions"]} == set(newer) and doc["subjects"][0]["questions"] == list(newer)
    old = {"subject": "s.a", "question": "hides-no-decision", "quote": "hides: a secret", "message": "No decision."}
    verdict = critic.judge(answer(["s.a"], [old]), g, asked=asked)
    assert not verdict.findings and "not asked" in verdict.refused[0]
    edited = graph({**DESIGN, "components/s/a.md": component(serves="n", hides="another secret")})
    assert critic.still_to_ask(edited, ledger) == {}  # changed text is judged against every question again
    assert critic.still_to_ask(g, stamped(g, Subject("s.a"), 2)) == {}  # judged under the current rubric


@realizes("arch.check.critique#AC8")
def test_a_component_with_code_is_judged_with_its_interface():
    code = {"src/s/__init__.py": "", "src/s/b.py": "def fetch(url: str, cached: bool) -> str:\n    return url\n"}
    facts = extract(Snapshot({SourcePath(k): v for k, v in code.items()}, Roots((SourcePath("src"),), ())))
    g = graph(DESIGN)
    (piece,) = critic.request(g, (Subject("s.b"),), facts).pieces
    assert "fetch(url: str, cached: bool) -> str" in piece.interface
    flag = {"subject": "s.b", "question": "interface-flag-picks-behaviour", "quote": "cached: bool",
            "message": "The flag picks between a cached and a fresh fetch."}
    assert critic.judge(answer(["s.b"], [flag]), g, facts).findings  # the interface can be quoted
    assert not critic.judge(answer(["s.b"], [flag]), g).findings  # without the code, the quote is not there
