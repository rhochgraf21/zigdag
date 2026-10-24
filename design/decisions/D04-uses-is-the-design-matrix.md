---
kind: decision
status: accepted
affects: [arch.model.matrix, arch.check.structure, arch.check.conformance, arch.guide.plan]
---
## Context
A design matrix drawn by hand is never verified against code.

## Decision
Declared `uses` among siblings are the matrix's off-diagonal entries. Coupled means a cycle; decoupled
means acyclic; uncoupled means none. The same declarations are the allowed imports, so the
independence axiom is checked on every run.

## Consequences
The matrix also drives realization order, parallel work plans and impact analysis. Non-code coupling
(shared resources, timing) is not captured yet; record it as a contradiction until a field earns its place.
