---
kind: component
realizes: Rank the most valuable next design actions within a scope
solution: Score open items (blocking findings, unlinked acceptance criteria, unserved needs, components below target maturity, coupled sets) by severity and closeness to needs
hides: The ranking heuristic
uses: [check.engine, method, model.graph, model.ids, model.schema]
status: specified
---
## Acceptance criteria
- AC1: The ranking shall be deterministic, with ties broken by id.
- AC2: Each item shall say what to do and which operation or method applies.
