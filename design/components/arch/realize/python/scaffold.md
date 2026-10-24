---
kind: component
realizes: Produce starting Python code for a component from its design
solution: Templates that create the package, a port module stub, and one property-test stub per acceptance criterion, each carrying `@realizes` links
hides: Templates
uses: [model.schema]
status: specified
---
## Acceptance criteria
- AC1: Scaffolding shall only create files that do not exist; existing files are reported and never modified.
- AC2: A freshly scaffolded component shall pass the type checker and produce no blocking `arch check` findings.

## Rationale
Scaffold once, then the code owns it (the root's decision: interfaces live in code). arch never regenerates code a person or agent has edited.
