---
kind: component
realizes: Divide a change into review pages, one topic per page, in an order where each can be decided without the later ones
solution: "A deck of typed pages: an overview; all changed needs and requirements on one page; the architecture before and after, per part whose children or their uses changed; all changed constraints on one page; design decisions; breaking or uncertain interfaces; code per component in build order, headed by the component, what it realizes, the needs it serves and its criteria; one batch of mechanical changes. Each page has a stable id, a digest of what it shows, a risk, and the pages it depends on"
hides: How a change is cut into items and how they are ordered
uses: [assess, change.diff, model.graph, model.ids, model.matrix, model.schema, realize.facts, realize.mapping, view.diagram, view.render]
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

