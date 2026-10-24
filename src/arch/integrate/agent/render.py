"""Methods rendered as agent skills, and the core skill for working with arch.

Part of arch.integrate.agent.
"""

from __future__ import annotations

from arch.guide.method import METHODS, Method, Step
from arch.integrate.agent.claude import SkillName
from arch.integrate.agent.commands import COMMANDS
from arch.model.ids import Text

CORE_SKILL = SkillName("arch")


def skill_name(method: Method) -> SkillName:
    return SkillName(f"arch-{method.name.value}")


def _step(i: int, step: Step) -> str:
    commands = "".join(f"\n   `{COMMANDS[op]}`" for op in step.uses)
    return f"{i}. {step.text}{commands}"


def method_skill(method: Method) -> Text:
    body = [
        "---",
        f"name: {skill_name(method)}",
        f"description: {method.title}. Use when: {method.when}",
        "---",
        f"# {method.title}",
        "",
        "**Inputs:** " + "; ".join(method.inputs),
        "",
        "## Steps",
        *(_step(i, s) for i, s in enumerate(method.steps, 1)),
        "",
        "## Done when",
        *(f"- {c}" for c in method.exit_criteria),
        "",
        "## Self-check",
        *(_step(i, s) for i, s in enumerate(method.self_check, 1)),
        "",
        "## Example",
        f"Situation: {method.example.situation}",
        "",
        f"Result: {method.example.lesson}",
        "",
    ]
    return Text("\n".join(body))


def core_skill() -> Text:
    methods = "\n".join(f"- `{skill_name(m)}`: {m.title}. {m.when}" for m in METHODS)
    return Text(f"""---
name: {CORE_SKILL}
description: Work in a project whose design is kept by arch (a design/ directory). Use before editing code or design files, when planning a change, or when unsure what to do next.
---
# Working with arch

The design in `design/` says what each component must do (`realizes`), how (`solution`), what it hides,
what it may use, and the criteria that prove it. arch checks the code against it.

1. **Orient:** `arch outline --depth 2`, then `arch next` for the most valuable next actions.
2. **Before editing a file:** `arch context <path>`. It tells you the component's purpose, its port, the
   criteria with their tests, the constraints in force (for example which effects are allowed), and what it
   may use. Stay within that.
3. **Change the design only through arch commands**, never by editing `design/` by hand. Run each with
   `--dry-run` first: `arch add`, `arch set`, `arch link`, `arch unlink`, `arch move`, `arch remove`, or a
   JSON batch with `arch apply`. Keep design changes in the same commit as the code they describe.
4. **Link tests to criteria** with `@realizes("component#ACn")` from `arch`.
5. **After changing anything:** `arch check`. Errors block; fix them, or change the design deliberately
   (with a decision entry: `arch add decision`).
6. **Reviewing:** `arch diff <base>` shows design changes by kind; read intent first.

Methods for design work:
{methods}
""")
