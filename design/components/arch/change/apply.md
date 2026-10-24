---
kind: component
realizes: Compute the resulting design and file edits for a batch of operations, rejecting batches that break integrity
solution: Apply operations to the immutable model in memory, run integrity rules on the result, then compute minimal text edits through the codec
hides: Transaction mechanics
uses: [ops, model.codec, model.graph, model.ids, model.schema, realize.facts, check]
status: specified
---
## Acceptance criteria
- AC1: apply shall be a pure function from (design, facts, operations) to (new design, edits, findings).
- AC2: A batch shall be rejected if an operation's precondition fails or if it introduces new integrity findings (S000, S001, S011); findings that existed before never block an edit.
- AC3: Edits shall be ordered and non-overlapping.
