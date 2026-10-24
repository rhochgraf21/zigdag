---
kind: component
realizes: Change the design through validated, reviewable operations
solution: Typed design operations applied atomically, producing file edits as data, plus a semantic diff between any two design states
hides: Edit semantics and diff computation
serves: [durable-knowledge, proportional-review]
uses: [model, realize, check]
exports: [ops, diff]
status: specified
---
## Acceptance criteria
- AC1: A batch of operations shall apply entirely or not at all.
- AC2: A batch that introduces integrity errors (dangling references, invalid nodes, cycles in the hierarchy) shall be rejected with those findings; quality findings shall be reported and shall not block.
- AC3: Applying operations shall produce file edits as data; writing them belongs to the workspace.
- AC4: The diff between two design states shall be computable from their files alone, for example HEAD and the working tree.

## Rationale
There is no proposal store: git already provides staging, review and undo (D07).
