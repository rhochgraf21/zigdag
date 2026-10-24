---
kind: component
realizes: Make arch available inside the workflows where humans and agents already work
solution: A workspace shell that owns all I/O, one operation catalog, and thin surfaces over it (CLI, MCP server, agent skills and hooks, CI recipe)
hides: Transports, filesystem layout and environment detection
serves: [right-context, low-adoption-cost, catch-departures]
uses: [model, realize, check, change, view, guide]
status: specified
---
## Acceptance criteria
- AC1: Every operation shall behave identically from the CLI and from MCP, with the same inputs, outputs and failure semantics.
- AC2: arch shall be usable in a repository after a single install command, with no configuration.
