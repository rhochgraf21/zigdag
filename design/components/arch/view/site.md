---
kind: component
realizes: Offer a browsable picture of the whole design and its health
solution: A static HTML site generated from outline, diagram and context views, with overlays for maturity, findings, evidence and hotspots, and no server
hides: Site structure and assets
uses: [outline, diagram, context]
status: draft
---
## Acceptance criteria
- AC1: The site shall work from the local filesystem with no network access; all assets are vendored.
- AC2: Every page shall link to the design file it renders.

## Rationale
Deliberately last. The PR summary and the outline carry most of the value; a site nobody opens is ceremony.
