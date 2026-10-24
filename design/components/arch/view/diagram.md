---
kind: component
realizes: Show structure visually, in forms that stay stable across revisions
solution: A renderer-neutral diagram model (nested containment, dependencies within one level, design structure matrix) with change marks, rendered to Mermaid for pull requests and to ELK graph JSON for the site
hides: Diagram construction and target formats
uses: [model.graph, model.matrix, realize.facts, change.diff]
status: specified
---
## Acceptance criteria
- AC1: The same design shall produce byte-identical diagram output.
- AC2: A diff diagram shall show only changed nodes and their direct neighbours, marked added, removed or changed.
- AC3: Matrix rows and columns shall follow realization order, so a decoupled design appears lower-triangular.
- AC4: The matrix shall be able to overlay observed imports and co-change on declared uses, distinguishing declared, undeclared and hidden coupling (co-change without dependency).
