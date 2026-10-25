---
kind: component
realizes: Define every user-facing operation once, with typed inputs and outputs, so all surfaces stay consistent
solution: A registry of typed operations, each run the same way by the CLI, the MCP server and agent hooks
hides: How each operation orchestrates the core
publishes: The operations every surface offers, with their typed inputs and outputs
uses: [workspace, model, realize, check, change, view, guide, review]
status: specified
---
## Acceptance criteria
- AC1: Every operation shall declare whether it writes the design, and read operations shall never write.
- AC2: Every result shall be a typed object renderable as Markdown or JSON.
- AC3: Operation names and input schemas shall be versioned.
- AC4: Every operation shall take domain types and return a report that renders itself.
- AC5: When an operation is removed or renamed, the major version of the published operation schema shall change.
- AC6: Only the surfaces shall parse text into domain types.
- AC7: Every surface shall let anyone raise a finding and answer any finding, always with a reason.
