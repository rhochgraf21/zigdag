import json

from conftest import EXAMPLES

from zigdag.cli import main
from zigdag.core.findings import Report, Result, finding
from zigdag.core.log import Actor, Answer, Kind, Timestamp, answered_question, raised, read_log, without_answered
from zigdag import verifies

AT, BY = Timestamp("2026-11-04T10:00:00Z"), Actor("robert")


def problems(text):
    return [p.say for p in read_log(text)[1]]


@verifies("zigdag.core.workflow.log#edited-lines")
def test_raised_ids_are_worked_out_and_an_edited_line_is_caught():
    line = raised(AT, BY, Kind.DEFECT, "app.core", "it leaks", None)
    log, found = read_log(line)
    assert not found and log.threads[0].open
    edited = line.replace("it leaks", "it leaked")
    assert any("was the line edited" in p for p in problems(edited))


def test_malformed_lines_break_with_their_line_number():
    text = "\n".join(['not json', '{"event": "teleported"}', '{"event": "critiqued", "at": "yesterday", "by": "x",'
                      ' "on": "app", "digest": "0123456789abcdef"}', json.dumps({"event": "approved"})])
    found = read_log(text)[1]
    assert [f.span.line for f in found] == [1, 2, 3, 4]
    assert any("UTC time" in f.say for f in found) and any("needs" in f.say for f in found)


def test_an_answer_names_a_thread_or_a_question_never_both_or_neither():
    both = json.dumps({"event": "answered", "at": AT, "by": BY, "answer": "fixed", "say": "x", "id": "a",
                       "check": "c", "on": "o", "digest": "0123456789abcdef"})
    neither = json.dumps({"event": "answered", "at": AT, "by": BY, "answer": "fixed", "say": "x"})
    unknown = json.dumps({"event": "answered", "at": AT, "by": BY, "answer": "fixed", "say": "x", "id": "nope"})
    assert any("either" in p for p in problems(both)) and any("either" in p for p in problems(neither))
    assert any('no raised thread "nope"' in p for p in problems(unknown))


@verifies("zigdag.core.workflow.log#answered-once")
def test_an_answered_question_stays_answered_until_its_content_changes():
    question = finding(Result.QUESTION, "quality.measurable", "app#x", None, '"fast" is vague', "The app ... fast.")
    log, _ = read_log(answered_question(AT, BY, question, Answer.ACCEPTED, "fine here"))
    assert without_answered(Report((question,)), log).findings == ()
    changed = finding(Result.QUESTION, "quality.measurable", "app#x", None, '"fast" is vague', "The app ... fast!")
    assert without_answered(Report((changed,)), log).findings == (changed,)


@verifies("zigdag.core.workflow.log#keep", "zigdag.core.workflow#keep", "zigdag.cli#run")
def test_the_cli_raises_and_answers_into_an_append_only_log(tmp_path, capsys):
    project = tmp_path / "p"
    project.mkdir()
    for f in (EXAMPLES / "mojo2verus").rglob("*"):
        if f.is_file():
            target = project / f.relative_to(EXAMPLES / "mojo2verus")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.read_text())
    run = lambda *a: main(["--project", str(project), *a])  # noqa: E731
    assert run("raise", "defect", "nowhere", "x", "--by", "claude") == 2
    assert run("raise", "defect", "mojo2verus.core.emit", "emit imports the parser", "--by", "claude") == 0
    thread = capsys.readouterr().out.split()[-1]
    assert run("answer", thread, "fixed", "pre-parsed now", "--by", "claude", "--countermeasure", "nowhere") == 2
    assert run("answer", thread, "fixed", "pre-parsed now", "--by", "claude") == 0
    assert run("answer", thread, "fixed", "again", "--by", "claude") == 2
    lines = (project / "design" / "log.jsonl").read_text().splitlines()
    assert [json.loads(x)["event"] for x in lines] == ["raised", "answered"]
    assert "design/log.jsonl merge=union" in (project / ".gitattributes").read_text()
    capsys.readouterr()
    assert run("findings") == 0 and "0 open threads" in capsys.readouterr().out
