---
kind: component
realizes: Extract units, imports, public API, ports, contracts, effect uses and design links from Python source
solution: A stdlib `ast` visitor; effects inferred from a table of known effect sources and propagated through the project call graph; deal decorators and `@realizes(...)` links read syntactically
hides: AST traversal and the effect-source table
uses: [facts]
status: specified
---
## Acceptance criteria
- AC1: Public symbols shall be the names in `__all__` if it is defined, else top-level names without a leading underscore.
- AC2: A function shall have effect E if it calls a known source of E (direct) or a project function with effect E (transitive), computed to a fixed point.
- AC3: Calls that cannot be resolved statically shall yield effect `unknown`, never be assumed pure.
- AC4: Relative imports shall resolve to absolute module paths.
- AC5: `@deal.has(...)` and `@deal.pre/post/ensure/inv` on public symbols shall become ContractDecl facts.

## Status
Effects (AC2, AC3) are not analyzed yet, so Python units do not claim that capability and
`check.conformance` reports effect constraints as not analyzed (C007).

## Rationale
Static inference over-approximates in places and misses dynamic dispatch. Reporting `unknown` keeps
it honest; deal's runtime checks on declared-pure ports remain the backstop.
