"""The Claude Code adapter for agents: skill files, the hooks in .claude/settings.json, and what the hooks say.

Uses only documented hook behaviour: a SessionStart hook's output is added to the agent's context, and a Stop hook
that exits 2 shows its stderr to the agent, which then carries on.

The check runs when the agent ends its turn, not after each edit: partway through a change the code is unfinished, so
most of what a check finds then is what the agent is about to fix anyway.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import NewType

import deal

from zigdag.agents.skills import SKILLS, Skill
from zigdag.core.findings import RecordPath
from zigdag.core.measures import Count
from zigdag.core.names import ShellCommand
from zigdag.core.texts import FileText, Shown

PRODUCT = "claude"
SKILLS_DIR = ".claude/skills"
SKILL_FILE = "SKILL.md"
SETTINGS = ".claude/settings.json"
HOOK_TIMEOUT_S = 30
HookEvent = NewType("HookEvent", str)  # what an agent's hook reports: a session starting, or a turn ending
Payload = NewType("Payload", str)  # the JSON an agent gives a hook on its standard input
SESSION_START = HookEvent("session-start")
TURN_END = HookEvent("turn-end")
FEEDBACK_EXIT = 2  # Claude Code shows a Stop hook's stderr to the agent when it exits with this
SESSION_NEXT_STEPS = 6  # lines of `zigdag next` in what a session starts with
_HOOK_EVENTS = ("SessionStart", "Stop")  # Claude Code's names for the events zigdag hooks into
_RETIRED_EVENTS = ("PostToolUse",)  # where earlier versions hooked in: an install takes zigdag's hook out of them
_CONTINUING = "stop_hook_active"  # set in a Stop payload when the agent carries on because a hook spoke


def skill_file(skill: Skill) -> str:
    return f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n{skill.body.lstrip()}"


@deal.post(lambda result: len(result) == len(SKILLS) and all(
    p.startswith(f"{SKILLS_DIR}/") and p.endswith(f"/{SKILL_FILE}") for p in result))
def skill_files() -> Mapping[RecordPath, FileText]:
    """Path (relative to the project) -> text, for every skill."""
    return {f"{SKILLS_DIR}/{s.name}/{SKILL_FILE}": skill_file(s) for s in SKILLS.values()}


def _hook(command: str, event: str) -> dict[str, object]:
    return {"type": "command", "command": f"{command} hook {event}", "timeout": HOOK_TIMEOUT_S}


def _ours(group: object, command: str) -> bool:
    hooks = group.get("hooks", []) if isinstance(group, dict) else []
    return any(isinstance(h, dict) and str(h.get("command", "")).startswith(f"{command} hook ") for h in hooks)


def _registered_once(settings: FileText, command: ShellCommand) -> bool:
    """Whether each of zigdag's hooks is in the settings exactly once."""
    hooks = json.loads(settings)["hooks"]
    return all(sum(_ours(g, command) for g in hooks[event]) == 1 for event in _HOOK_EVENTS)


@deal.ensure(lambda current, command, result: result is None or _registered_once(result, command))
def merged_settings(current: FileText | None, command: ShellCommand) -> FileText | None:
    """The settings with zigdag's two hooks registered once, everything else left as it was; None when the current
    settings are not a JSON object whose hooks are lists by event, and so cannot be merged."""
    try:
        settings = json.loads(current) if current and current.strip() else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(settings, dict):
        return None
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict) or not all(isinstance(hooks.get(e, []), list) for e in _HOOK_EVENTS):
        return None
    start, stop = _HOOK_EVENTS
    wanted = {
        start: {"hooks": [_hook(command, SESSION_START)]},
        stop: {"hooks": [_hook(command, TURN_END)]},
    }
    for event, group in wanted.items():
        hooks[event] = [g for g in hooks.get(event, []) if not _ours(g, command)] + [group]
    for event in _RETIRED_EVENTS:
        if isinstance(hooks.get(event), list):
            hooks[event] = [g for g in hooks[event] if not _ours(g, command)]
    return json.dumps(settings, indent=2) + "\n"


@deal.post(lambda result: isinstance(result, bool))
def told_already(payload: Payload) -> bool:
    """Whether a Stop payload says the agent is already carrying on because a hook spoke. Speaking again then would
    keep an agent that cannot fix a break from ever stopping."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and data.get(_CONTINUING) is True


@deal.ensure(lambda shown, next_steps, open_threads, result: shown in result and result.startswith(
    "This project's design is kept by zigdag"))
def session_text(shown: Shown, next_steps: Shown, open_threads: Count) -> Shown:
    """What an agent reads as a session starts: the system at a glance, and what is to do."""
    lines = ["This project's design is kept by zigdag (design/*.yaml). Use the zigdag skill before changing code.", "",
             shown, "", *next_steps.splitlines()[:SESSION_NEXT_STEPS]]
    if open_threads:
        lines.append(f"{open_threads} open threads in the log: zigdag findings")
    return "\n".join(lines)
