---
kind: component
realizes: Resolve what the names in Python source refer to
solution: A module scope of imports and definitions, widened inside functions by self and typed parameters, and each local's setting line
hides: How Python scopes are followed to find what a name means
uses: [facts]
status: specified
---
## Acceptance criteria
- AC1: Names in code shall resolve to their definitions through imports, typed parameters and self.
- AC2: Each use of a local variable shall resolve to the line that set the value it sees.

