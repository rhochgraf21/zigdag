"""The Claude Code adapter for agents: skill files, the hooks in .claude/settings.json, and what the hooks say.

Uses only documented hook behaviour: a SessionStart hook's output is added to the agent's context, and a PostToolUse
hook that exits 2 shows its stderr to the agent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import NewType

from zigdag.agents.skills import SKILLS, Skill
from zigdag.core.checks.run import Analysis
from zigdag.core.record.read import DESIGN_DIR
from zigdag.core.settings import SETTINGS_FILE
from zigdag.core.findings import Finding, Result
from zigdag.core.findings import RecordPath
from zigdag.core.measures import Count
from zigdag.core.names import ProjectRoot, ShellCommand
from zigdag.core.texts import FileText, Shown, Written

PRODUCT = "claude"
SKILLS_DIR = ".claude/skills"
SKILL_FILE = "SKILL.md"
SETTINGS = ".claude/settings.json"
EDIT_TOOLS = "Edit|Write|MultiEdit|NotebookEdit"  # the tools whose use the post-edit hook follows
HOOK_TIMEOUT_S = 30
HookEvent = NewType("HookEvent", str)  # what an agent's hook reports: a session starting, or a file edited
Payload = NewType("Payload", str)  # the JSON an agent gives a hook on its standard input
SESSION_START = HookEvent("session-start")
POST_EDIT = HookEvent("post-edit")
FEEDBACK_EXIT = 2  # Claude Code shows a PostToolUse hook's stderr to the agent when it exits with this
SESSION_NEXT_STEPS = 6  # lines of `zigdag next` in what a session starts with


def skill_file(skill: Skill) -> str:
    return f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n{skill.body.lstrip()}"


def skill_files() -> Mapping[RecordPath, FileText]:
    """Path (relative to the project) -> text, for every skill."""
    return {f"{SKILLS_DIR}/{s.name}/{SKILL_FILE}": skill_file(s) for s in SKILLS.values()}


def _hook(command: str, event: str) -> dict[str, object]:
    return {"type": "command", "command": f"{command} hook {event}", "timeout": HOOK_TIMEOUT_S}


def _ours(group: object, command: str) -> bool:
    hooks = group.get("hooks", []) if isinstance(group, dict) else []
    return any(isinstance(h, dict) and str(h.get("command", "")).startswith(f"{command} hook ") for h in hooks)


def merged_settings(current: FileText | None, command: ShellCommand) -> FileText | None:
    """The settings with zigdag's two hooks registered once, everything else left as it was; None when the current
    settings are not a JSON object, and so cannot be merged."""
    try:
        settings = json.loads(current) if current and current.strip() else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(settings, dict):
        return None
    hooks = settings.setdefault("hooks", {})
    wanted = {
        "SessionStart": {"hooks": [_hook(command, SESSION_START)]},
        "PostToolUse": {"matcher": EDIT_TOOLS, "hooks": [_hook(command, POST_EDIT)]},
    }
    for event, group in wanted.items():
        hooks[event] = [g for g in hooks.get(event, []) if not _ours(g, command)] + [group]
    return json.dumps(settings, indent=2) + "\n"


def edited_path(payload: Payload) -> Written | None:
    """The file a PostToolUse payload says was edited, or None."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    tool_input = data.get("tool_input", {}) if isinstance(data, dict) else {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    return path if isinstance(path, str) else None


def session_text(shown: Shown, next_steps: Shown, open_threads: Count) -> Shown:
    """What an agent reads as a session starts: the system at a glance, and what is to do."""
    lines = ["This project's design is kept by zigdag (design/*.yaml). Use the zigdag skill before changing code.", "",
             shown, "", *next_steps.splitlines()[:SESSION_NEXT_STEPS]]
    if open_threads:
        lines.append(f"{open_threads} open threads in the log: zigdag findings")
    return "\n".join(lines)


def _is_record(path: str) -> bool:
    return path == SETTINGS_FILE or path.startswith(DESIGN_DIR + "/")


def relevant(analysis: Analysis, root: ProjectRoot, edited: Written | None) -> list[Finding]:
    """The breaks an edit should hear about: in the file it edited, about the DP that file is, or anywhere in the
    record when the record was edited."""
    if edited is None:
        return []
    path = Path(edited).resolve() if Path(edited).is_absolute() else root / edited
    if not path.is_relative_to(root):
        return []
    rel = path.relative_to(root).as_posix()
    breaks = analysis.report.of_result(Result.BREAKS)
    if _is_record(rel):
        return [f for f in breaks if f.span is not None and _is_record(f.span.path)]
    dp = analysis.dp_of_file(rel)
    return [f for f in breaks if (f.span is not None and f.span.path == rel) or (dp is not None and analysis.is_under(f, dp))]
