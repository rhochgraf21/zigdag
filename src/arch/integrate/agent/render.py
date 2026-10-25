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
5. **Describe the interface names you add or change.** Give each exported function, class and field one line
   (a docstring, or a comment at the end of a field's line). Say what its name and type cannot: its purpose,
   its units or invariants, where the value comes from, or what `None` means. Skip it when the type already
   says it (`path: SourcePath`). Do not comment local variables: name them well instead. People read these
   lines when they point at a name in review. `arch check --all` lists names that need one (C014) and
   descriptions that only repeat the name (C015).
6. **After changing anything:** `arch check`. Errors block; fix them, change the design deliberately (with a
   decision entry: `arch add decision`), or answer the finding with a reason (`arch respond`).
7. **Raise what you notice, in your work or anyone's.** A defect, a question, or a better way:
   `arch raise defect|question|idea <subject> "<what>" --station <where it was made> --evidence "<exact
   words>" --by <you>`. Do not fix what is outside your task. An idea must say what it removes or unifies,
   and what it costs; the best ideas make things simpler with a stronger model or abstraction, not more
   parts. Read `arch findings --all` first, and do not raise again what was declined without new evidence.
8. **Answer findings:** `arch respond fixed|accepted|declined|answered "<reason>" <ref...> --by <you>`, with
   refs as `arch findings` lists them. Every answer is reviewed. When the finding was noticed later than the
   station that made it (an escape), also give `--countermeasure`: what changes upstream so it is caught
   where it is made next time.
9. **Before asking for review, inspect your own output.** Run `arch review <base>` and read it as the reviewer
   will: every reason, every "No reason given", every question about a description. Fix what you would flag.
   When the change is something a person must see (a page, a layout), ask them to look at the named things
   before calling it done. Do not pass a defect downstream.
10. **Being reviewed:** a person reviews your change item by item with `arch review --serve`. Before that,
   point them at what matters with `arch review --note <item> "..."` (where you were unsure, what to
   check). Afterwards, `arch review --feedback` lists their open change requests, blocking ones first;
   address each one. You cannot approve items yourself.
11. **Reviewing someone else's change:** `arch review <base>` summarises it layer by layer; read intent first.

Methods for design work:
{methods}
""")
