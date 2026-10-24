---
kind: decision
status: accepted
affects: [arch.realize, arch.realize.facts, arch.realize.treesitter, arch.check.conformance]
---
## Context
arch should support languages beyond Python (TypeScript, and Mojo would be great), without a
hand-built semantic adapter per language and without pretending to know what it does not.

## Decision
Two tiers behind one fact schema. Structural (tree-sitter grammar plus a query file): units, imports,
public symbols, links. Semantic (language-specific): adds ports, contracts and effects. Every unit
records the capabilities analyzed, and checks needing a missing capability report "not analyzed".
Python's semantic adapter uses stdlib `ast`, not tree-sitter, because it is exact and dependency-free.

## Consequences
Breadth is cheap and honest. Effect constraints are only enforced where a semantic adapter exists, and
reports say so. Unit names are adapter-defined dotted segments, so cross-language imports (Mojo → Python)
are representable.
