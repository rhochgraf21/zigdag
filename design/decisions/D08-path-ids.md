---
kind: decision
status: accepted
affects: [arch.model.codec, arch.model.graph, arch.realize.mapping, arch.change.ops]
---
## Decision
A component's id is its path under `design/components/` with dots. The directory tree is the
decomposition; the parent comes from the path. For Python the id doubles as the default module path,
so `arch.check.baseline` lives in `src/arch/check/baseline`. References resolve by lexical scope, so
siblings are written by short name.

## Consequences
Browsing the design on GitHub shows the hierarchy. Ids change on re-parenting, which `move` handles by
rewriting every reference, including links in code.
