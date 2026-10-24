---
kind: component
realizes: Define every user-facing operation once, with typed inputs and outputs, so all surfaces stay consistent
solution: A registry of typed operations, each run the same way by the CLI, the MCP server and agent hooks
hides: How each operation orchestrates the core
uses: [workspace, model, realize, check, change, view, guide, review]
status: specified
---
## Acceptance criteria
- AC1: Every operation shall declare whether it writes the design, and read operations shall never write.
- AC2: Every result shall be a typed object renderable as Markdown or JSON.
- AC3: Operation names and input schemas shall be versioned.
- AC4: Every operation shall take domain types and return a report that renders itself.
- AC5: Removing or renaming an operation shall count as a breaking change.
- AC6: Only the surfaces shall parse text into domain types.
