---
kind: component
realizes: Divide a change into items a reviewer can decide one at a time, in an order where each can be decided without the later ones
solution: Typed items (readiness, each intent and design change, structure, each breaking or uncertain port, each component's code with tests first, a batch of mechanical changes), each with a stable id, a digest of what it shows, a risk and the items it depends on
hides: How a change is cut into items and how they are ordered
uses: [assess, change.diff, model.graph, model.ids, model.matrix, realize.facts, realize.mapping, view.diagram, view.render]
status: specified
---
## Acceptance criteria
- AC1: Code items shall come per component in build order, with the component's tests before its source.
- AC2: An item's digest shall change exactly when what the item shows changes.
- AC3: Lock files, renames without changes and formatting-only edits shall go into one mechanical batch instead of code items.

