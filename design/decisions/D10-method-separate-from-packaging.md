---
kind: decision
status: accepted
affects: [arch.guide.method, arch.integrate.agent]
---
## Context
Agent skills mention concrete commands. With skills in `guide`, any rename in `integrate.catalog`
would break them: guide's requirement depends on a later design parameter (upper-triangular entry).

## Decision
Split them. `guide.method` holds the reasoning procedures in terms of abstract operations;
`integrate.agent` renders them into product-specific skills with real commands from the catalog.
(TRIZ: separation by system level.)

## Consequences
The second coupling caught by the matrix. Methods can be reused by any surface, and they can be
tested by worked examples without an agent product.
