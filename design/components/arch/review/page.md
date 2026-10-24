---
kind: component
realizes: Show a review one item at a time so a reviewer can decide each without leaving the page
solution: "One self-contained HTML document: every item rendered in Python (deltas, SVG diagrams, diffs labelled by the definition they fall in, the component's criteria and constraints beside its code), a small script for keyboard navigation and posting verdicts, light and dark themes, no external assets"
hides: Page layout and interaction
uses: [items, session, model.ids, realize.facts, view.diagram, view.render]
status: specified
---
## Acceptance criteria
- AC1: The page shall load no external resources.
- AC2: Every item shall be reachable by keyboard, and approving shall move to the next undecided item.

