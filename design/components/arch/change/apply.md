---
kind: component
realizes: Compute the resulting design and file edits for a batch of operations, rejecting batches that break integrity
solution: Apply operations to the immutable model in memory, run integrity rules on the result, then compute minimal text edits through the codec
hides: How a draft of the design is kept while operations run
uses: [ops, model.codec, model.graph, model.ids, model.schema, realize.facts, check]
status: specified
---
## Acceptance criteria
- AC1: apply shall be a pure function from (design, facts, operations) to (new design, edits, findings).
- AC2: If an operation's precondition fails, or the batch adds new integrity findings, then the batch shall be rejected.
- AC3: Edits shall be ordered and non-overlapping.
- AC4: Findings that existed before a batch shall never block it.
