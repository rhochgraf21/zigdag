---
kind: decision
status: accepted
affects: [arch.guide.infer, arch.realize]
---
## Context
Brownfield inference was first placed in `realize`. It outputs design operations, so realize would use
change, while change uses check and check uses realize: a coupled set in the level-1 matrix.

## Decision
Inference is a heuristic advisor that proposes operations, so it lives in `guide`, which already sits
after both realize and change. realize stays a pure facts layer.

## Consequences
The level-1 matrix is lower-triangular again. The first coupling the method caught in its own design.
