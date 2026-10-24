---
kind: component
realizes: Name things and places in the design, consistently for every other part of the model
solution: Distinct id types (component, need, constraint, criterion), text and location value types, issues, and the operations on ids (parent, containment, criterion parts)
hides: How ids are spelled and compared
uses: []
status: specified
---
## Acceptance criteria
- AC1: Containment shall be decided by dotted segments, so `a.bc` is not within `a.b`.
- AC2: A criterion reference shall split into its component and its label, and a bare component id shall have no label.

## Decisions
### A vocabulary layer below the schema
- Chose: ids, text, locations and issues in their own component at the bottom of the model.
- Over: keeping them in `schema`.
- Because: typed policies name components, and the schema holds policies; with ids in the schema, `schema` and `policy` would use each other, a coupled pair.
- Previously: ids lived in `schema`; split out when typed policies were introduced.
