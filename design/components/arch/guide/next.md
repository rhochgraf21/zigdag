---
kind: component
realizes: Rank the most valuable next design actions within a scope
solution: A score for each open problem by its severity and its closeness to a need
hides: The ranking heuristic
uses: [check.engine, method, model.graph, model.ids, model.schema]
status: specified
---
## Acceptance criteria
- AC1: The ranking shall be deterministic, with ties broken by id.
- AC2: Each item shall say what to do and which operation or method applies.
