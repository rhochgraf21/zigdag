---
kind: component
realizes: Derive the design matrix of a component's children, classify it, and order the children for realization
solution: Declared sibling uses are the off-diagonal entries; strongly connected components identify coupled sets; topological layering gives realization order and parallel layers
hides: Matrix construction and ordering algorithms
uses: [graph]
status: specified
---
## Acceptance criteria
- AC1: The matrix shall be classified uncoupled if there are no sibling uses, decoupled if sibling uses are acyclic, and coupled otherwise.
- AC2: For a coupled matrix, the result shall list each coupled set so it can be resolved or recorded as a contradiction.
- AC3: Ordering shall be deterministic, with ties broken by id.
- AC4: Layers shall group children so that every child in layer n uses only children in layers below n.

## Rationale
Using declared dependencies as the matrix makes the independence axiom checkable against code (uses
become the allowed imports) instead of a diagram nobody verifies. See D04.
