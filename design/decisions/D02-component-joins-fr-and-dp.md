---
kind: decision
status: accepted
affects: [arch.model.schema]
---
## Context
Axiomatic design keeps functional requirements and design parameters as separate objects. In an ideal
(uncoupled) design they pair one-to-one, so separate files double node count and indirection.

## Decision
One Component node holds an FR (`realizes`), its DP (`solution`) and the DP's secret (`hides`). Design
matrix entries are the component's `uses`. Four node kinds in total: need, component, constraint, decision.

## Consequences
Half the files, with the AD vocabulary kept in methods and docs. Cost: one FR satisfied jointly by several
DPs must be split into several FRs, which AD recommends anyway.
