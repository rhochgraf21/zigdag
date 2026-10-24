---
kind: component
realizes: Make arch available inside the workflows where humans and agents already work
solution: A workspace that does all input and output, one catalog of operations, and thin surfaces over the catalog
hides: Transports, filesystem layout and environment detection
serves: [right-context, low-adoption-cost, catch-departures]
uses: [model, realize, check, change, view, guide, review]
status: specified
---
## Acceptance criteria
- AC1: Every operation shall behave identically from the CLI and from MCP, with the same inputs, outputs and failure semantics.
- AC2: arch shall be usable in a repository after a single install command, with no configuration.
