---
kind: component
realizes: Put arch into coding agents' edit loops without anyone having to remember to use it
solution: Skill packages rendered from guide.method with concrete operations from the catalog, plus hook configurations that inject the context card before an edit and run a scoped check after it; one adapter per agent product, with a generic AGENTS.md fallback
hides: Agent-specific formats and hook mechanisms
uses: [catalog, guide.method]
status: specified
---
## Acceptance criteria
- AC1: Installing shall be idempotent, shall write only under the project's agent configuration paths, and shall list those paths before writing.
- AC2: Hooks shall finish within the edit-loop budget, or skip with a notice rather than block the agent.
- AC3: Every product-specific adapter shall be optional; the generic fallback shall work with any agent.

## Rationale
The difference between a tool you have to remember and a tool that is just there. Why packaging lives
here and method content lives in guide is recorded on guide.method.
