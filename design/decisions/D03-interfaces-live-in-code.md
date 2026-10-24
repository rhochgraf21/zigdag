---
kind: decision
status: accepted
affects: [arch.model.schema, arch.realize, arch.realize.python.scaffold]
---
## Context
Writing signatures and contract expressions in design files means code in YAML: no type checker, no
editor support, duplicated and bound to drift.

## Decision
If something can be expressed in code, it lives in code: ports, contracts, domain types and property
tests. The design holds what code cannot express (intent, solution choice, secret, rationale, policy) and
links to code by id (`@realizes("arch.check.baseline#AC2")`). arch reads ports back as facts for views
and diffs. Scaffolding creates code once; after that the code owns it.

## Consequences
One source of truth per fact. Humans review design files that contain only decisions. Test for any
proposed field: would two senior engineers argue about it in a design review? If not, derive it.
