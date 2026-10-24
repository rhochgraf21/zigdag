---
kind: component
realizes: Offer a browsable picture of the whole design and its health
solution: A static HTML site generated from outline, diagram and context views, with overlays for maturity, findings, evidence and hotspots, and no server
hides: Site structure and assets
uses: [outline, diagram, context]
status: draft
---
## Acceptance criteria
- AC1: The site shall work from the local filesystem with no network access.
- AC2: Every page shall link to the design file it renders.
- AC3: The site shall include every asset it needs.

## Rationale
Deliberately last. The PR summary and the outline carry most of the value; a site nobody opens is ceremony.
