---
kind: component
realizes: Compute the resulting design and file edits for a batch of operations, rejecting batches that break integrity
solution: Apply operations to the immutable model in memory, run integrity rules on the result, then compute minimal text edits through the codec
hides: Transaction mechanics
uses: [ops, model.codec, model.graph, realize.facts, check]
status: specified
---
## Acceptance criteria
- AC1: apply shall be a pure function from (design, facts, operations) to (new design, edits, findings).
- AC2: Applying a batch and then its inverse shall restore byte-identical files.
- AC3: Edits shall be ordered and non-overlapping.
