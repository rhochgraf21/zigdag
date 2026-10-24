---
kind: component
realizes: Divide a change into review pages that a reviewer can decide in order
solution: A deck of pages, one topic per page, from needs and requirements to the code of each component
hides: How a change is cut into items and how they are ordered
uses: [assess, change.diff, model.graph, model.ids, model.matrix, model.schema, realize.facts, realize.mapping, view.diagram, view.render, model.codec, explain]
status: specified
---
## Acceptance criteria
- AC1: Code pages shall come per component in build order, with the component's tests before its source.
- AC2: An item's digest shall change exactly when what the item shows changes.
- AC3: Lock files, renames without changes and formatting-only edits shall go into one mechanical batch instead of code pages.
- AC4: All changed needs and requirements shall be on one page, each requirement with the needs it serves and its changed criteria with their evidence.
- AC5: Each part of the system whose children, or the uses between them, changed shall be shown before and after.
- AC6: All changed constraints shall be on one page, each with its scope and its rule in plain words, before and after.
- AC7: Each code hunk shall be labelled with the definition it falls in and the criteria that definition is linked to.
- AC8: When a component's uses change, the after diagram shall mark that component as changed.
- AC9: A follow-on code change shall be shown with the interface change it follows, on the page of the component that defines that interface.
- AC10: The overview shall count the code changes that give no reason.

