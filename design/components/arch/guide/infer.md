---
kind: component
realizes: Draft a decomposition for code that has no design yet
solution: Propose components from package structure, refined by import clustering and co-change, emitted as a batch of add and link operations at status draft
hides: Clustering heuristics
uses: [realize.facts, change.ops]
status: specified
---
## Acceptance criteria
- AC1: Inferred components shall have status draft, so prose rules (statements, missing secrets) report at info level.
- AC2: Inferred uses shall equal the observed component-level imports, so a freshly inferred design has no boundary findings.
- AC3: Where observed imports form cycles, the coupled set shall be reported as a proposed contradiction rather than hidden.

## Rationale
Adoption starts green and then tightens; the first check on an existing repo must not be a wall of red.
Moved here from realize to resolve a coupling (D09).
