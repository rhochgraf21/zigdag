---
kind: component
realizes: Give every view one vocabulary for what it renders
solution: Markdown and JSON value types, sizes and counts, and the Rendering protocol every report implements
publishes: The value types and the rendering protocol every view and report uses
uses: []
status: specified
---
## Acceptance criteria
- AC1: Every view and report shall render through the Rendering protocol, returning Markdown and JSON values rather than bare strings and dictionaries.
