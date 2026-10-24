---
kind: component
realizes: Maintain an explicit, checked model of a software system's intent and structure that humans and agents use to understand and change it
solution: A local, deterministic design toolchain (library, CLI, MCP server, agent skills) over plain-text design files kept in the repository
hides: How design knowledge is stored, related to code, and verified
serves: [understand-system, right-context, catch-departures, proportional-review, trace-purpose, sound-reasoning, low-adoption-cost, compose-at-scale, durable-knowledge]
uses: []
status: specified
---
## Acceptance criteria
- AC1: When pointed at a repository that has no design, arch shall produce useful output (dependency map, design structure matrix, hotspots, draft decomposition) without any authored input.
- AC2: When a change introduces a departure from the design, arch shall report it naming the component, the rule and the source location, and signal failure; departures that existed before adoption shall not signal failure.
- AC3: For any component or source location, arch shall produce a context card within a configurable size budget (default ~4k tokens).
- AC4: arch shall never require network access, an account, or a particular coding agent.
- AC5: arch's own design shall be maintained with arch and pass `arch check` with an empty baseline.

## Rationale
The bet: if the design is the cheapest *correct* context an agent can get, and the review it produces is the
cheapest *correct* review a human can do, the design gets kept current because doing so pays off immediately.
Every child serves one of those two ends.
