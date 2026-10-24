---
kind: component
realizes: Answer structural questions about the design, covering ancestry, children, uses, visibility, inherited constraints and traceability to needs
solution: An immutable indexed graph built once per load, with hierarchy taken from dotted ids and references resolved by lexical scope
hides: Index structures and lookup algorithms
uses: [schema]
status: specified
---
## Acceptance criteria
- AC1: The parent of a component shall be derived from its id; no parent field exists.
- AC2: A reference `n` written in component c shall resolve to the nearest ancestor of c that has a descendant path `n` (lexical scoping), or to an unresolved reference if none does.
- AC3: effective_constraints(c) shall be the constraints whose `applies_to` names c or an ancestor of c; components do not list constraints themselves.
- AC4: may_use(a, b) shall hold only if b (or an ancestor of b) is in the uses of a, and b is visible to a: b is a child of an ancestor of a, or is reachable from one through exported children.
- AC5: needs_of(c) shall return the needs served by c, or by its nearest ancestor that declares any.

## Rationale
Visibility works like Go's `internal/` or Bazel visibility: siblings and uncles are visible,
grandchildren of others only if exported. Encapsulation is then a property of the design, not a convention.
