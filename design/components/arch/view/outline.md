---
kind: component
realizes: Present the decomposition as a readable outline at a chosen depth
solution: An indented tree of id and realizes, with status and finding markers, limited by depth and subtree
hides: Formatting
uses: [model.graph, model.matrix, model.schema]
status: specified
---
## Acceptance criteria
- AC1: Siblings shall be listed in realization order, so reading top-down follows dependency order.
- AC2: Depth n shall show exactly n levels below the root of the view.
