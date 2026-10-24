---
kind: component
realizes: Judge how risky each changed file is and what evidence each touched criterion has
solution: A documented risk score for each changed file, and the evidence for each criterion the change touches
hides: The risk weights
uses: [change.diff, check.engine, model.graph, model.ids, model.schema, realize.facts, realize.history, realize.mapping]
status: specified
---
## Acceptance criteria
- AC1: Each changed file shall get a risk of high, medium or low with the reasons that produced it, by the score documented in the module.
- AC2: When a component is verified, its linked evidence passes and its ports are unchanged, its files shall score one lower.
- AC3: A file's risk shall count only the interface changes to names defined in that file.
- AC4: Every criterion of a component that the change adds shall get evidence.

