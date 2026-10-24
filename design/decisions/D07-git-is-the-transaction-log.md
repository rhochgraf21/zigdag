---
kind: decision
status: accepted
affects: [arch.change]
---
## Context
An earlier idea had `propose`, `apply` and `reject` backed by a proposal store.

## Decision
Operations apply directly to the working tree (atomically, validated, with `--dry-run`). Git provides
staging, review, history and undo; the design diff is computed against any revision.

## Consequences
One less concept and no state outside version control. Design changes ride in the same commit as the
code that realizes them.
