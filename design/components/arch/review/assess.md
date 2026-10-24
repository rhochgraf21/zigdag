---
kind: component
realizes: Judge how risky each changed file is and what evidence each touched criterion has
solution: A documented risk score per changed file (port changes, new dependencies between components, new findings, evidence, hotspots, size) and a verdict per added or reworded criterion
hides: The risk weights
uses: [change.diff, check.engine, model.graph, model.ids, model.schema, realize.facts, realize.history, realize.mapping]
status: specified
---
## Acceptance criteria
- AC1: Each changed file shall get a risk of high, medium or low with the reasons that produced it, by the score documented in the module.
- AC2: When a component is verified, its linked evidence passes and its ports are unchanged, its files shall score one lower.

