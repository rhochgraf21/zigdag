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

## Decisions
### Git is the transaction log
- Chose: operations apply directly to the working tree (atomic, validated, with `--dry-run`); the design diff is computed against any revision.
- Over: propose, apply and reject commands backed by a proposal store.
- Because: git already provides staging, review, history and undo, so this is one less concept with no state outside version control.
- Consequences: design changes ride in the same commit as the code that realizes them.
