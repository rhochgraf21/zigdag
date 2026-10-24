from __future__ import annotations

import io
import json

from arch import realizes
from arch.guide.method import AbstractOp
from arch.integrate import agent
from arch.integrate.agent.commands import COMMANDS
from arch.integrate.cli import _parser, main
from arch.integrate.workspace import Workspace
from tests.conftest import NEED, component


def project(tmp_path, extra=None):
    files = {"design/needs/n.md": NEED, "design/components/app.md": component(serves="n"),
             "design/components/app/core.md": component(serves="n"), "src/app/__init__.py": "",
             "src/app/core.py": "", **(extra or {})}
    for path, text in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    return Workspace(tmp_path)


@realizes("arch.integrate.agent#AC4")
def test_every_operation_has_a_real_command():
    assert set(COMMANDS) == set(AbstractOp)
    commands = set(_parser()._subparsers._group_actions[0].choices)
    assert {c.split()[1] for c in COMMANDS.values()} <= commands


@realizes("arch.integrate.agent#AC1", "arch.integrate.agent#AC3")
def test_install_is_idempotent_and_keeps_existing_settings(tmp_path):
    settings = {"permissions": {"allow": ["Bash(ls)"]},
                "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine"}]}]}}
    ws = project(tmp_path, {".claude/settings.json": json.dumps(settings), "AGENTS.md": "# House rules\n"})
    plan = agent.installation(ws, agent.Product.CLAUDE_CODE)
    paths = {e.path for e in plan.edits}
    assert {".claude/skills/arch/SKILL.md", ".claude/skills/arch-decompose/SKILL.md", "AGENTS.md", ".claude/settings.json"} <= paths
    ws.write_project(plan.edits)
    merged = json.loads((tmp_path / ".claude/settings.json").read_text())
    assert merged["permissions"] == settings["permissions"]
    assert [g["matcher"] for g in merged["hooks"]["PostToolUse"]] == ["Bash", "Edit|Write"]
    assert merged["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "arch hook session-start"
    assert (tmp_path / "AGENTS.md").read_text().startswith("# House rules\n")
    assert agent.installation(ws, agent.Product.CLAUDE_CODE).edits == ()  # nothing left to change
    generic = agent.installation(project(tmp_path / "g"), agent.Product.GENERIC)
    assert [e.path for e in generic.edits] == ["AGENTS.md"]


def test_method_skills_name_commands_not_operations():
    text = agent.render.method_skill(agent.render.METHODS[2])
    assert "`arch matrix <component>`" in text and "AbstractOp" not in text


@realizes("arch.integrate.agent#AC6")
def test_post_edit_reports_blocking_findings_about_the_edited_component(tmp_path):
    ws = project(tmp_path, {"src/app/core.py": "import app.other\n", "src/app/other.py": "",
                            "design/components/app/other.md": component(serves="n")})
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(tmp_path / "src/app/core.py")}})
    response = agent.handle(agent.HookEvent.POST_EDIT, ws, payload)
    assert response.exit is agent.HookExit.FEEDBACK and "C001" in response.stderr
    clean = json.dumps({"tool_input": {"file_path": str(tmp_path / "src/app/other.py")}})
    assert agent.handle(agent.HookEvent.POST_EDIT, ws, clean).exit is agent.HookExit.OK
    start = agent.handle(agent.HookEvent.SESSION_START, ws, "")
    assert "arch context" in start.stdout and "core" in start.stdout and len(start.stdout) < 10_000


@realizes("arch.integrate.agent#AC5", "arch.integrate.agent#AC2")
def test_hooks_never_break_the_agent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert main(["--project", str(tmp_path), "hook", "post-edit"]) == 0  # no design here at all
    project(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert main(["--project", str(tmp_path), "hook", "post-edit"]) == 0
