---
kind: component
realizes: Answer structural questions about the design, covering ancestry, children, uses, visibility, inherited constraints and traceability to needs
solution: An immutable indexed graph built once per load, with hierarchy taken from dotted ids and references resolved by lexical scope
hides: Index structures and lookup algorithms
publishes: The questions any part may ask about the design's structure
uses: [ids, policy, schema]
status: specified
---
## Acceptance criteria
- AC1: The parent of a component shall be derived from its id, with no separate parent field.
- AC2: A reference `n` written in component c shall resolve to the nearest ancestor of c that has a descendant path `n` (lexical scoping), or to an unresolved reference if none does.
- AC3: A component's constraints shall be those whose scope names the component or one of its ancestors.
- AC4: The graph shall let a component use another only if it declares that use and the other is visible to it.
- AC5: needs_of(c) shall return the needs served by c, or by its nearest ancestor that declares any.
- AC6: A component shall be visible to another if it is a child of one of the other's ancestors, or is exported on the way down.

## Rationale
Visibility works like Go's `internal/` or Bazel visibility: siblings and uncles are visible,
grandchildren of others only if exported. Encapsulation is then a property of the design, not a convention.
