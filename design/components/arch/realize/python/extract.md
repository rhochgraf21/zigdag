---
kind: component
realizes: Extract units, imports, public API, ports, contracts, effect uses and design links from Python source
solution: A visitor over Python's syntax tree that reads imports, interfaces, contracts and links, and infers effects
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
- AC6: Every resolvable call shall become a Call fact naming the callee's dotted name, resolving `self.method()`, imported names, and methods on parameters or locals whose class is known from an annotation or a constructor call.
- AC7: The extractor shall record the parameter, return and class-field types of public symbols, each with its leaf type names, excluding containers and literals.
- AC8: Names in code shall resolve to their definitions through imports, typed parameters and self.
- AC9: A member of a private class shall not be part of the interface.
- AC10: Each use of a local variable shall resolve to the line that set the value it sees.
- AC11: A module value set to a short literal shall read as a constant, with its value.

## Rationale
Static inference over-approximates in places and misses dynamic dispatch. Reporting `unknown` keeps
it honest; deal's runtime checks on declared-pure ports remain the backstop.

## Decisions
### Charge effects where access to an effectful API is obtained
- Chose: an effect is recorded where code names an effectful API (an import such as `os` or `subprocess`, `open`, the clock), and reaches every caller arch can resolve; a method call on an object that was merely handed in is charged where that object was obtained, not to the code using it.
- Over: treating every unresolved call as `unknown`, or every unresolved call as pure.
- Because: treating all unresolved calls as unknown would flood pure components with warnings; treating them as pure would pass silently. Charging effects where access is obtained matches the functional-core design (the core receives data, not handles) and keeps a pure finding meaningful.
- Consequences: a core function that is handed an effectful object and calls it is not caught statically; deal's runtime checks on declared-pure ports remain the backstop. Truly dynamic code (`eval`, `exec`, dynamic imports) is reported as `unknown`.

### Distinctive pathlib methods count on any receiver
- Chose: in units that use pathlib, calls such as `.read_text()`, `.rglob()` or `.mkdir()` count as file effects whatever the receiver is.
- Over: tracking the types of all local values.
- Because: paths are usually passed around unannotated, and these method names are rare elsewhere; ambiguous names (`resolve`, `replace`, `open` on unknown receivers) are left out to avoid false findings.
