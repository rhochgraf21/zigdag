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
- AC2: When a batch would introduce integrity errors, the change shall be rejected with those findings.
- AC3: Applying operations shall produce file edits as data, which the workspace writes.
- AC4: The diff between two design states shall be computable from their files alone, for example HEAD and the working tree.
- AC5: Quality findings from a batch shall be reported without blocking it.

## Decisions
### Git is the transaction log
- Chose: operations apply directly to the working tree (atomic, validated, with `--dry-run`); the design diff is computed against any revision.
- Over: propose, apply and reject commands backed by a proposal store.
- Because: git already provides staging, review, history and undo, so this is one less concept with no state outside version control.
- Consequences: design changes ride in the same commit as the code that realizes them.
