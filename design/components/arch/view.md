---
kind: component
realizes: Present the design to each actor at the level of detail their task needs
solution: Pure renderers that produce Markdown, JSON and diagram models for context cards, outlines, diagrams and matrices, review summaries and a static site
hides: Selection, formatting and layout
serves: [understand-system, right-context, proportional-review]
uses: [model, realize, check, change, guide]
exports: [context, outline, diagram, render, report, review]
status: specified
---
## Acceptance criteria
- AC1: Every view shall be available as Markdown for humans and as JSON for agents, with the same content.
- AC2: Views shall contain no timestamps or other run-dependent values.
- AC3: Every element in a view shall link back to the design file it came from.
