---
kind: component
realizes: Express each kind of design edit as a typed operation with preconditions
solution: A closed set of operations (add, set, remove, move, link, unlink) that serialize as JSON validated by a published schema
hides: Operation semantics and preconditions
uses: [model.schema]
status: specified
---
## Acceptance criteria
- AC1: Every operation shall be expressible as a JSON object validated by the published schema.
- AC2: `move` shall rewrite every reference to the moved subtree, including `@realizes` links in code.
- AC3: Removing a component that has children or inbound uses shall be refused unless the operation says `cascade`.
- AC4: Every operation shall have an inverse.
