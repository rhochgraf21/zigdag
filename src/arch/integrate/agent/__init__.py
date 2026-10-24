"""Put arch into coding agents' edit loops (arch.integrate.agent).

Installation produces project-file edits (skills, AGENTS.md, hook settings) as data; the workspace writes
them. Hook handlers return what to print and the exit code; the CLI does the printing.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from arch.check import check
from arch.check.engine import Finding
from arch.guide.method import METHODS
from arch.integrate.agent import claude
from arch.integrate.agent.render import CORE_SKILL, core_skill, method_skill, skill_name
from arch.integrate.catalog import ProjectEdit, ProjectPath, Workspace
from arch.model.graph import Graph
from arch.model.ids import ComponentId, Text, is_within
from arch.realize.facts import Facts
from arch.realize.mapping import map_units
from arch.view.outline import outline

AGENTS_MD = ProjectPath("AGENTS.md")
_BEGIN, _END = "<!-- arch:begin -->", "<!-- arch:end -->"
MAX_SESSION_CONTEXT = 9_000  # Claude Code caps hook context at 10,000 characters


class Product(enum.Enum):
    CLAUDE_CODE = "claude-code"
    GENERIC = "generic"  # AGENTS.md only, read by most agents


class HookEvent(enum.Enum):
    SESSION_START = "session-start"
    POST_EDIT = "post-edit"


class HookExit(enum.Enum):
    OK = 0
    FEEDBACK = 2  # Claude Code shows stderr to the model


@dataclass(frozen=True)
class HookResponse:
    stdout: Text = Text("")
    stderr: Text = Text("")
    exit: HookExit = HookExit.OK


@dataclass(frozen=True)
class Installation:
    product: Product
    edits: tuple[ProjectEdit, ...]

    def to_markdown(self) -> str:
        if not self.edits:
            return f"{self.product.value}: already installed, nothing to change"
        lines = [f"{self.product.value}: writes {len(self.edits)} files"]
        lines += [f"  {'create' if e.before is None else 'update'} {e.path}" for e in self.edits]
        return "\n".join(lines)

    def to_json(self) -> dict[str, object]:
        return {"product": self.product.value,
                "edits": [{"path": e.path, "action": "create" if e.before is None else "update"} for e in self.edits]}


def installation(ws: Workspace, product: Product, command: str = "arch") -> Installation:
    """The files to write so `product` uses arch; idempotent (unchanged files are left out)."""
    wanted: list[tuple[ProjectPath, str]] = [(AGENTS_MD, _agents_md(ws.read_project_file(AGENTS_MD)))]
    if product is Product.CLAUDE_CODE:
        wanted.append((claude.skill_path(CORE_SKILL), core_skill()))
        wanted += [(claude.skill_path(skill_name(m)), method_skill(m)) for m in METHODS]
        wanted.append((claude.SETTINGS, claude.merged_settings(ws.read_project_file(claude.SETTINGS), command)))
    edits = []
    for path, text in wanted:
        before = ws.read_project_file(path)
        if before != text:
            edits.append(ProjectEdit(path, before, text))
    return Installation(product, tuple(edits))


def _agents_md(current: str | None) -> str:
    block = f"{_BEGIN}\n{core_skill().split('---', 2)[2].strip()}\n{_END}\n"
    if current and _BEGIN in current and _END in current:
        head, rest = current.split(_BEGIN, 1)
        return head + block + rest.split(_END, 1)[1].lstrip("\n")
    return (current.rstrip("\n") + "\n\n" if current else "") + block


def handle(event: HookEvent, ws: Workspace, payload: str) -> HookResponse:
    if event is HookEvent.SESSION_START:
        return _session_start(ws)
    return _post_edit(ws, payload)


def _session_start(ws: Workspace) -> HookResponse:
    g = Graph(ws.design())
    report = check(g, ws.facts(), ws.baseline())
    top = outline(g, None, 1).to_markdown()
    blocking = len(report.blocking)
    text = (f"This project's design is kept by arch in design/. Top level:\n{top}\n\n"
            "Before editing a file, run `arch context <path>`. Change the design only with arch commands "
            "(`--dry-run` first). After changes, run `arch check`; `arch next` shows what to do next. "
            f"Current state: {blocking} blocking finding{'s' * (blocking != 1)}.")
    return HookResponse(stdout=Text(text[:MAX_SESSION_CONTEXT]))


def _post_edit(ws: Workspace, payload: str) -> HookResponse:
    path = claude.edited_path(payload)
    rel = ws.relative(Path(path)) if path else None
    if rel is None:
        return HookResponse()
    g = Graph(ws.design())
    facts = ws.facts()
    report = check(g, facts, ws.baseline())
    focus = _component_of(g, facts, rel)
    related = [f for f in report.blocking if _about(f, rel, focus)]
    if not related:
        return HookResponse()
    lines = [f"arch check found {len(related)} blocking problem{'s' * (len(related) != 1)} after editing {rel}:"]
    lines += [f"- {f.rule} {f.subject}: {f.message} (hint: {f.hint})" for f in related[:20]]
    return HookResponse(stderr=Text("\n".join(lines)), exit=HookExit.FEEDBACK)


def _component_of(g: Graph, facts: Facts, rel: ProjectPath) -> ComponentId | None:
    unit = next((u for u in facts.units if u.path == rel), None)
    return map_units(g, facts).component_of.get(unit.name) if unit else None


def _about(f: Finding, rel: ProjectPath, focus: ComponentId | None) -> bool:
    """A finding located in the edited file, or about the component the file belongs to."""
    if f.location is not None and f.location.path in (rel, rel.removeprefix("design/")):
        return True
    return focus is not None and is_within(ComponentId(f.subject), focus)


__all__ = ["HookEvent", "HookExit", "HookResponse", "Installation", "Product", "handle", "installation"]
