---
kind: component
realizes: Compute the semantic difference between two design states
solution: Match nodes by id, compare field by field, detect renames by content when ids differ, and classify each change
hides: Matching and rename detection
uses: [model.graph]
status: specified
---
## Acceptance criteria
- AC1: The diff shall list added, removed, moved and changed nodes, with field-level changes for each.
- AC2: Each change shall be classified as intent (needs, realizes, acceptance criteria), structure (uses, exports, hierarchy), policy (constraints, budgets) or prose (rationale only).
- AC3: A change that only reformats shall yield an empty diff.

## Rationale
The classes map onto the layers of a review summary, so a reviewer reads intent changes first and prose last.
