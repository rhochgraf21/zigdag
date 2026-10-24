---
kind: component
realizes: Show a review as a deck of pages a reviewer flips through, deciding each without leaving it
solution: One self-contained HTML page per review, flipped with the arrow keys, with diagrams and highlighted code diffs
hides: Page layout and interaction
uses: [items, session, model.ids, realize.facts, view.diagram, view.render, explain]
status: specified
---
## Acceptance criteria
- AC1: The page shall load no external resources.
- AC2: The left and right arrow keys shall flip pages, every action shall have a key, and approving shall move to the next undecided page.
- AC3: An architecture page shall draw before and after on one layout, so each component sits in the same place in both and shows what it realizes.
- AC4: When the reviewer points at an id, the page shall show what the id means.
- AC5: Each page shall open with one plain sentence that says what it shows and what the reviewer decides.
- AC6: A diagram legend shall list only the change colours that the diagrams use.
- AC7: Each code change shall show the signature and description of the definition it is in.
- AC8: When the reviewer points at a name in the code, the page shall show what the name refers to.

