---
kind: component
realizes: Represent needs, components and constraints, with the decisions behind them, as a persistent, recursive design that can be queried
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

## Decisions
### Ids are paths
- Chose: a component's id is its path under `design/components/` with dots; the directory tree is the decomposition; references resolve by lexical scope; for Python the id is also the default module path.
- Over: opaque stable ids with a separate parent field.
- Because: browsing the design shows the hierarchy, and nothing derivable is stored twice.
- Consequences: re-parenting changes ids, so `move` rewrites every reference, including links in code.
