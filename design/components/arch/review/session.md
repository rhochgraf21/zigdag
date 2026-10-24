---
kind: component
realizes: Keep a reviewer's verdicts on items, and tell the author what is still to do
solution: Verdicts (approve, request changes, comment; with category, weight and anchor) recorded against item digests in a versioned JSON session; feedback and a record rendered from it
hides: How verdicts are stored and when they go stale
uses: [items, model.ids, view.render]
status: specified
---
## Acceptance criteria
- AC1: When an item changes after a verdict, the item shall be stale, and an earlier change request on it shall no longer count as open.
- AC2: When an item has changes requested, the items that depend on it shall show as blocked.
- AC3: Feedback shall list open change requests, blocking ones first, each with its category, comment, anchor and item id.

