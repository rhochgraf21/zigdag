---
kind: component
realizes: Represent needs, components, constraints and decisions as a persistent, recursive design that can be queried
solution: An immutable typed domain model with a lossless text codec and structural and matrix queries
hides: Internal representation and indexing of the design
serves: [durable-knowledge, compose-at-scale, trace-purpose]
uses: []
exports: [schema, codec, graph, matrix]
status: specified
---
## Acceptance criteria
- AC1: A component at any depth shall have the same kind and fields as the root.
- AC2: When a design is loaded and rendered with no edits, every file shall be byte-identical to its input.
- AC3: Every query shall be a pure function of the loaded design.

## Rationale
One recursive kind at every scale is what lets checks, views and plans work identically on a
module-sized component and a system-sized one.
