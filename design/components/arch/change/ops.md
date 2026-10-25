---
kind: component
realizes: Express each kind of design edit as a typed operation with preconditions
solution: A closed set of typed operations that serialize as JSON, match a published schema, and check their preconditions on the draft before editing
hides: How each operation becomes field and section edits on the draft
uses: [model.codec, model.graph, model.ids, model.schema, realize.facts]
status: specified
---
## Acceptance criteria
- AC1: Every operation shall be expressible as a JSON object validated by the published schema.
- AC2: `move` shall rewrite every reference to the moved subtree, including `@realizes` links in code.
- AC3: Removing a component that has children or inbound uses shall be refused unless the operation says `cascade`.
- AC4: Setting a field back to its old value, and unlinking what was linked, shall restore the file byte for byte (git is the undo for everything else).
- AC6: When a split moves criteria into a new component, every test linked to them shall link to their new ids.
- AC7: If a split would leave its component with no criteria, then the split shall be rejected.

## Decisions
### Operations edit through a Draft
- Chose: each operation changes the design only through the Draft protocol defined here, field by field and section by section
- Over: operations that read and write design files themselves
- Because: apply can then run every operation against one working copy, check the result, and write all of it or none; and an operation that edits fields and sections by name, through the codec's edit model, cannot reformat what people wrote
- Backed by: pure-core
