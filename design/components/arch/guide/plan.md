---
kind: component
realizes: Show what a change to some components affects, and which work can proceed in parallel and in what order
solution: The reverse-uses closure of the targets gives impact; realization layers from the design matrix, restricted to that closure, give order and parallelism
hides: Impact and scheduling algorithms
uses: [model.matrix, model.graph, model.schema]
status: specified
---
## Acceptance criteria
- AC1: Components in the same layer shall have no uses between them, so they can be given to separate agents.
- AC2: Given target components, the plan shall include every component that uses them, directly or transitively, with the acceptance criteria to re-verify.
