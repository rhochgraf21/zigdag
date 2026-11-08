"""Phase 3: entry digests, review, gates, critique, approval, rename, and the agent's skills and hooks."""

import json
import subprocess
from pathlib import Path

from conftest import FUNCTIONAL, project
from test_code import build

from zigdag import verifies
from zigdag.agents import claude
from zigdag.cli import main
from zigdag.core.checks.gates import check_gates
from zigdag.core.critique import read_answer, request
from zigdag.core.log import Actor, Answer, Kind, Timestamp, answered_thread, approved, critiqued, raised, read_log
from zigdag.core.record.entries import EntryKind, entries
from zigdag.core.record.read import read_record
from zigdag.core.rename import rename
from zigdag.core.review import ChangeKind, diff
from zigdag.core.rubric import RUBRIC, RUBRIC_VERSION

AT, PERSON, AGENT = Timestamp("2026-11-04T10:00:00Z"), Actor("robert"), Actor("claude")
GATES = """
critique-first:
  kind: workflow
  on: app
  serves: [verify-programs.wrong-proof-passes]
  gate: critique-before-review
person-approves:
  kind: workflow
  on: app
  serves: [verify-programs.wrong-proof-passes]
  gate: person-approves-design
countermeasures:
  kind: workflow
  on: app
  serves: [verify-programs.wrong-proof-passes]
  gate: countermeasure-on-escape
"""


def record(functional: str = FUNCTIONAL, process: str = GATES):
    return read_record({"design/functional.yaml": functional, "design/process.yaml": process})[0]


@verifies("zigdag.core.record#digest")
def test_an_entry_gets_a_new_digest_only_when_its_content_changes():
    a, b = entries(record()), entries(record())
    assert a["app.core"].digest == b["app.core"].digest
    changed = entries(record(FUNCTIONAL.replace("Verus source text.", "Verus.")))
    assert changed["app.core"].digest != a["app.core"].digest and changed["app"].digest == a["app"].digest
    assert a["critique-first"].kind is EntryKind.PROCESS_VARIABLE


@verifies("zigdag.core.workflow.review#show", "zigdag.core.workflow.review#renames")
def test_review_finds_additions_changes_removals_and_renames():
    before = record()
    moved = FUNCTIONAL.replace("app.core:", "app.engine:").replace("The core shall", "The engine shall")
    after = record(moved + "  app.cli:\n    serves: [verify-programs.wrong-proof-passes]\n    statements:\n"
                   "      run: The cli shall run.\n")
    kinds = {c.entry.name: c.kind for c in diff(before, after)}
    assert kinds["app.cli"] is ChangeKind.ADDED
    assert kinds["app.engine"] is ChangeKind.ADDED  # its statements changed, so it is no rename
    same = record(FUNCTIONAL.replace("app.core:", "app.engine:"))
    renames = [c for c in diff(before, same) if c.kind is ChangeKind.RENAMED]
    assert [c.entry.name for c in renames] == ["app.engine"] and renames[0].before.name == "app.core"


@verifies("zigdag.core.analysis.checks#gates")
def test_gates_need_a_current_critique_then_a_person():
    r = record()
    changed = [entries(r)["app.core"]]
    entry = changed[0]
    log = read_log("")[0]
    rules = {f.rule for f in check_gates(r, log, ("robert",), changed, False)}
    assert rules == {"critique-first", "person-approves"}
    lines = [critiqued(AT, AGENT, entry.name, entry.digest, RUBRIC_VERSION),
             approved(Timestamp("2026-11-04T11:00:00Z"), AGENT, entry.name, entry.digest)]
    log = read_log("\n".join(lines))[0]
    assert {f.rule for f in check_gates(r, log, ("robert",), changed, False)} == {"person-approves"}
    lines.append(approved(Timestamp("2026-11-04T12:00:00Z"), PERSON, entry.name, entry.digest))
    assert not list(check_gates(r, read_log("\n".join(lines))[0], ("robert",), changed, False))


def test_a_fixed_defect_needs_a_countermeasure():
    r = record()
    line = raised(AT, PERSON, Kind.DEFECT, "app.core", "it leaks", None)
    thread = json.loads(line)["id"]
    bare = read_log("\n".join([line, answered_thread(AT, AGENT, thread, Answer.FIXED, "done", None)]))[0]
    assert [f.rule for f in check_gates(r, bare, (), None, False)] == ["countermeasures"]
    kept = read_log("\n".join([line, answered_thread(AT, AGENT, thread, Answer.FIXED, "done", "app.core")]))[0]
    assert not list(check_gates(r, kept, (), None, False))


@verifies("zigdag.core.workflow.critique#ask", "zigdag.core.workflow.critique#quotes")
def test_a_critique_asks_the_rubric_and_refuses_made_up_evidence():
    r = record()
    entry = entries(r)["app.core"]
    text, asked = request(r, read_log("")[0], [entry])
    req = json.loads(text)
    assert asked == 1 and {q["id"] for q in req["entries"][0]["questions"]} == {q.id for q in RUBRIC[EntryKind.FR]}
    answer = {"entries": [{"name": "app.core", "digest": entry.digest, "findings": [
        {"question": "fr-function", "kind": "question", "say": "which text?", "evidence": "Mojo source text"},
        {"question": "fr-function", "kind": "defect", "say": "made up", "evidence": "not in the entry"},
    ]}]}
    judged, problems = read_answer(entries(r), json.dumps(answer))
    assert len(judged[0].findings) == 1 and any("not words from the entry" in p for p in problems)
    stale = json.dumps({"entries": [{"name": "app.core", "digest": "0" * 16, "findings": []}]})
    assert "changed since" in read_answer(entries(r), stale)[1][0]
    again, _ = request(r, read_log(critiqued(AT, AGENT, entry.name, entry.digest, RUBRIC_VERSION))[0], [entry])
    assert json.loads(again)["entries"] == []  # nothing new to ask at this content and rubric


@verifies("zigdag.core.workflow.rename#everywhere")
def test_rename_changes_every_use_and_no_other_name():
    functional = FUNCTIONAL + """
  app.core.parse:
    statements:
      read: The parse shall read source text.
constraints:
  limits:  # why
    on: app.core
    serves: [verify-programs.wrong-proof-passes]
    check: may-depend-on
    with:
      allow: [app.core.parse, app.cored, lark]
"""
    tests = {"tests/test_a.py": 'from zigdag import verifies\n\n\n@verifies("app.core#translate", "app.cored#x")\n'
                                "def test_a():\n    pass\n"}
    changed, missed = rename({"design/functional.yaml": functional}, tests, "app.core", "app.engine")
    out = changed["design/functional.yaml"]
    assert not missed and "app.engine.parse:" in out and "on: app.engine" in out and "app.cored" in out
    assert "The engine shall translate" in out and "limits:  # why" in out
    assert '@verifies("app.engine#translate", "app.cored#x")' in changed["tests/test_a.py"]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@verifies("zigdag.cli#run", "zigdag.core.workflow.rename#keeps-code")
def test_review_approve_and_rename_through_the_command_line(tmp_path, capsys):
    root = build(tmp_path)
    settings = root / "zigdag.toml"
    settings.write_text(settings.read_text().replace("ruleset = 1", 'ruleset = 1\npeople = ["robert"]'))
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    functional = root / "design/functional.yaml"
    functional.write_text(functional.read_text().replace("price an order in cents", "price an order in whole cents"))
    run = lambda *a: main(["--project", str(root), *a])  # noqa: E731
    assert run("review", "HEAD") == 0  # no gates in force: nothing blocks
    assert "~ FR tiny.core.rules" in capsys.readouterr().out
    assert run("approve", "--base", "HEAD", "--by", "robert") == 0
    assert run("rename", "tiny.core.rules", "tiny.core.pricing") == 0
    assert "tiny.core.pricing: [tiny.core.rules]" in (root / "design/physical.yaml").read_text()
    assert run("check") in (0, 1) and "tiny.core.pricing" in (root / "tests/test_tiny.py").read_text()


@verifies("zigdag.agents#install", "zigdag.agents#feedback")
def test_the_agent_gets_skills_hooks_and_feedback_on_its_edits(tmp_path, capsys, monkeypatch):
    assert claude.merged_settings("not json", "zigdag") is None
    once = claude.merged_settings('{"permissions": {}}', "zigdag")
    twice = claude.merged_settings(once, "zigdag")
    assert once == twice and json.loads(once)["permissions"] == {}
    assert all(text.startswith("---\nname: ") for text in claude.skill_files().values())
    root = build(tmp_path)
    assert main(["--project", str(root), "agent", "install", "claude"]) == 0
    assert (root / ".claude/skills/zigdag/SKILL.md").is_file()
    payload = json.dumps({"tool_input": {"file_path": str(root / "src/tiny/core/rules.py")}})
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(payload))
    capsys.readouterr()
    assert main(["--project", str(root), "hook", "post-edit"]) == claude.FEEDBACK_EXIT
    assert "pure-core" in capsys.readouterr().err
    assert main(["--project", str(root), "hook", "session-start"]) == 0


def test_a_minimal_record_with_gates_still_holds_without_a_base():
    assert not project(process=GATES).breaks
