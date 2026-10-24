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

## Decisions
### No language model inside arch
- Chose: deterministic rules in `check`; judgement in `guide.method` procedures run by the user's own agent, each ending in arch's deterministic self-check.
- Over: built-in model calls for critique and generation.
- Because: arch stays offline, reproducible, cheap and agent-neutral, and its judgement improves as agents improve without arch changing.
- Consequences: no built-in critique for people who run arch without an agent.
- Backed by: no-network, agent-neutral.

### Interfaces and contracts live in code
- Chose: ports, contracts, domain types and tests live in code and link to the design by id (`@realizes("x#AC2")`); arch reads them back as facts; scaffolding creates code once, then the code owns it.
- Over: signatures and contract expressions in design files.
- Because: in design files they would be code with no type checker or editor support, duplicated and bound to drift. A field belongs in the design only if two senior engineers would argue about it in a design review.
- Consequences: design files hold only decisions; views show interfaces by reading the code.

### Functional core, imperative shell
- Chose: all I/O in `integrate.workspace` (files, git) and the CLI and MCP surfaces (stdio); extraction is a pure function of file contents, and applying operations returns edits as data.
- Over: I/O wherever it is convenient.
- Because: nearly all of arch becomes property-testable and cacheable by content hash, and arch obeys the effect constraints it asks users to adopt.
- Consequences: effect facts must separate direct from transitive use, because code that calls the shell is effectful without touching I/O itself.
- Backed by: pure-core, shell-io.

### Rigor without ceremony
- Chose: maturity levels whose checks tighten over time (TRIZ: separation in time); the coding agent, already present, writes the design through validated operations (ASIT: closed world); views that improve the agent's own work, so the design pays its way every day.
- Over: one strictness for everything, or people writing design files by hand.
- Because: adding structure improves verifiability but worsens upkeep effort, and a design that costs more than it saves rots.
