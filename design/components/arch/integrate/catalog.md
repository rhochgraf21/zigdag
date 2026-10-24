---
kind: component
realizes: Define every user-facing operation once, with typed inputs and outputs, so all surfaces stay consistent
solution: A registry of operations (init, context, outline, check, baseline, add, set, move, remove, link, apply, diff, review, next, plan, infer, scaffold, diagram, site), each a function from workspace and typed input to a typed result, with descriptions used to generate CLI help, MCP tool schemas and skill references
hides: How each operation orchestrates the core
uses: [workspace, model, realize, check, change, view, guide]
status: specified
---
## Acceptance criteria
- AC1: Every operation shall declare whether it writes the design, and read operations shall never write.
- AC2: Every result shall be a typed object renderable as Markdown or JSON.
- AC3: Operation names and input schemas shall be versioned; removing or renaming one is a breaking change.
