---
kind: component
realizes: Draft a decomposition for code that has no design yet
solution: Propose components from package structure, refined by import clustering and co-change, emitted as a batch of add and link operations at status draft
hides: Clustering heuristics
uses: [change.ops, model.ids, model.matrix, model.schema, realize.facts, realize.mapping]
status: specified
---
## Acceptance criteria
- AC1: Inferred components shall have status draft, so prose rules (statements, missing secrets) report at info level.
- AC2: Inferred uses shall equal the observed component-level imports, with exports added where visibility needs them, so a freshly inferred design has no boundary findings (imports of a component's own ancestors are reported, and baselined by `arch init`).
- AC4: An inferred component shall realize the first line of its module's documentation when there is one.
- AC5: `arch init` shall write the inferred design and a baseline of whatever errors remain, so the first `arch check` passes.
- AC3: Where observed imports form cycles, the coupled set shall be proposed as an accepted coupling for review, rather than hidden.

## Rationale
Adoption starts green and then tightens; the first check on an existing repo must not be a wall of red.

## Decisions
### Inference belongs to guide
- Chose: a heuristic advisor in `guide` that proposes design operations.
- Over: an extraction step in `realize`.
- Because: inference outputs design operations, so in `realize` it would use `change`, while `change` uses `check` and `check` uses `realize`: a coupled set in arch's top-level matrix.
- Previously: lived in `realize`; moved when the matrix showed the cycle.
