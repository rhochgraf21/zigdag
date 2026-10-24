"""The Claude Code adapter: skill files, hook registration, and hook handling.

Part of arch.integrate.agent. Uses only documented hook behaviour: SessionStart stdout is added to the
model's context; a PostToolUse hook that exits 2 shows its stderr to the model.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import NewType

from arch.integrate.catalog import ProjectPath
from arch.model.ids import Text

HookPayload = NewType("HookPayload", str)  # the JSON Claude Code sends a hook on stdin
ArchCommand = NewType("ArchCommand", str)  # how a hook invokes arch, e.g. "arch" or "uv run arch"
SettingsText = NewType("SettingsText", str)  # the contents of .claude/settings.json
SkillName = NewType("SkillName", str)

SETTINGS = ProjectPath(".claude/settings.json")
SKILLS_DIR = ".claude/skills"
EDIT_TOOLS = "Edit|Write"
SESSION_TIMEOUT_S = 10
POST_EDIT_TIMEOUT_S = 30


class BadSettings(Exception):
    pass


def skill_path(name: SkillName) -> ProjectPath:
    return ProjectPath(f"{SKILLS_DIR}/{name}/SKILL.md")


def merged_settings(current: SettingsText | None, command: ArchCommand) -> SettingsText:
    """Settings with arch's hooks registered once, everything else left as it was."""
    try:
        settings = json.loads(current) if current else {}
    except json.JSONDecodeError as e:
        raise BadSettings(f"{SETTINGS} is not valid JSON ({e}); fix it before installing hooks") from None
    if not isinstance(settings, dict):
        raise BadSettings(f"{SETTINGS} must contain a JSON object")
    hooks = settings.setdefault("hooks", {})
    ours = {
        "SessionStart": {"hooks": [_handler(command, "session-start", SESSION_TIMEOUT_S)]},
        "PostToolUse": {"matcher": EDIT_TOOLS, "hooks": [_handler(command, "post-edit", POST_EDIT_TIMEOUT_S)]},
    }
    for event, group in ours.items():
        groups = [g for g in hooks.get(event, []) if not _is_ours(g, command)]
        hooks[event] = [*groups, group]
    return SettingsText(json.dumps(settings, indent=2) + "\n")


def _handler(command: str, event: str, timeout: int) -> Mapping[str, object]:
    return {"type": "command", "command": f"{command} hook {event}", "timeout": timeout}


def _is_ours(group: object, command: str) -> bool:
    handlers = group.get("hooks", []) if isinstance(group, dict) else []
    return any(isinstance(h, dict) and str(h.get("command", "")).startswith(f"{command} hook ") for h in handlers)


def edited_path(payload: HookPayload) -> Text | None:
    """The absolute file path a PostToolUse payload for Edit/Write names, if any."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    tool_input = data.get("tool_input") if isinstance(data, dict) else None
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    return Text(path) if isinstance(path, str) else None
