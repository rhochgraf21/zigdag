---
kind: component
realizes: Put arch into coding agents' edit loops without anyone having to remember to use it
solution: Skill packages rendered from guide.method with concrete operations from the catalog, plus hook configurations that inject the context card before an edit and run a scoped check after it; one adapter per agent product, with a generic AGENTS.md fallback
hides: Agent-specific formats and hook mechanisms
uses: [catalog, check, guide.method, model.graph, model.ids, realize.facts, realize.mapping, view.outline]
status: specified
---
## Acceptance criteria
- AC1: Installing shall be idempotent, shall write only under the project's agent configuration paths, and shall list those paths before writing.
- AC2: Hooks shall finish within the edit-loop budget, or skip with a notice rather than block the agent.
- AC3: Every product-specific adapter shall be optional; the generic fallback shall work with any agent.
- AC4: Every abstract operation a method names shall have a command spelling, and every spelled command shall exist in the CLI.
- AC5: A hook run outside an arch project, or one that fails, shall exit quietly so it never breaks the agent.
- AC6: After an edit, the hook shall report only blocking findings about the edited file or its component, through Claude Code's documented feedback channel (exit 2, stderr).

## Rationale
The difference between a tool you have to remember and a tool that is just there. Why packaging lives
here and method content lives in guide is recorded on guide.method.

## Decisions
### Use only documented hook behaviour
- Chose: SessionStart output for orientation (added to the model's context) and PostToolUse exit 2 with stderr for blocking findings after an edit.
- Over: injecting the context card before each edit through PreToolUse.
- Because: the documentation confirms the first two; context injection on PreToolUse without a permission decision is undocumented, and a hook that misbehaves inside an agent's loop costs more trust than it earns.
- Consequences: the agent is told to run `arch context` itself before editing; the core skill and AGENTS.md say so.

### Agent commands live in the adapter
- Chose: `arch agent install` and `arch hook` are served by integrate.agent, which the CLI calls directly.
- Over: catalog operations.
- Because: the agent adapter uses the catalog, so the catalog cannot use the adapter without a cycle.
