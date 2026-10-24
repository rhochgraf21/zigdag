---
kind: decision
status: accepted
affects: [arch.integrate.workspace, arch.realize, arch.change.apply]
---
## Context
Design-time tools quietly gain file I/O everywhere, which makes them hard to test and cache.

## Decision
All I/O lives in `integrate.workspace` (files, git) and the two surfaces (stdio). Even language
extraction is a pure function over file contents, and applying operations returns edits as data.
Effect facts distinguish direct from transitive use, because orchestrators that call the shell are
effectful transitively without touching I/O themselves.

## Consequences
Almost all of arch is property-testable and memoizable by content hash. arch dogfoods the effect
constraints it asks users to adopt.
