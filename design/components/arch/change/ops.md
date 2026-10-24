---
kind: component
realizes: Express each kind of design edit as a typed operation with preconditions
solution: A closed set of typed operations that serialize as JSON and are checked against a published schema
hides: Operation semantics and preconditions
uses: [model.codec, model.graph, model.ids, model.schema, realize.facts]
status: specified
---
## Acceptance criteria
- AC1: Every operation shall be expressible as a JSON object validated by the published schema.
- AC2: `move` shall rewrite every reference to the moved subtree, including `@realizes` links in code.
- AC3: Removing a component that has children or inbound uses shall be refused unless the operation says `cascade`.
- AC4: Setting a field back to its old value, and unlinking what was linked, shall restore the file byte for byte (git is the undo for everything else).
- AC5: Each operation shall apply itself to a Draft protocol defined here, so operations never handle files or transactions.
