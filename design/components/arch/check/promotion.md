---
kind: component
realizes: Decide when a part may claim it has passed a station
solution: A status may rise only when nothing is open at the stations it newly claims
hides: What each status claims
uses: [engine, model.graph, model.ids]
status: specified
---
## Acceptance criteria
- AC1: When a change raises a status while a defect or question at a newly claimed station is open, the change shall be rejected.

