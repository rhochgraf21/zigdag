---
kind: component
realizes: Show a review as a deck of pages a reviewer flips through, deciding each without leaving it
solution: "One self-contained HTML document: every page rendered in Python (text diffs side by side, before and after diagrams on one layout, syntax-highlighted code diffs with each hunk's definition and criteria), a small design system with light and dark themes, a script for arrow-key flipping, a stepper by topic and posting verdicts; no external assets"
hides: Page layout and interaction
uses: [items, session, model.ids, realize.facts, view.diagram, view.render]
status: specified
---
## Acceptance criteria
- AC1: The page shall load no external resources.
- AC2: The left and right arrow keys shall flip pages, every action shall have a key, and approving shall move to the next undecided page.
- AC3: An architecture page shall draw before and after on one layout, so each component sits in the same place in both and shows what it realizes.

