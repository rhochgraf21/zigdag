---
kind: component
realizes: Detect structural defects in the design
solution: Rules over the design graph that flag broken references, untraced parts, coupling, missing secrets and loosened constraints
hides: The structural rule set
uses: [engine, model.graph, model.ids, model.matrix, model.schema]
status: specified
---
## Acceptance criteria
- AC1: A coupled sibling set shall be a defect at the solution station.
- AC2: A component with more than nine children shall be a question at the solution station.
- AC3: A non-root component without `hides` shall be a defect at the solution station.
- AC4: A use that reaches outside the component's parent (beyond its siblings and their parts) shall be an error unless the parent may use the target.
- AC5: An `accepts_coupling` entry whose members are no longer coupled shall be a warning.
- AC6: A decision entry without `Chose:` and `Because:` lines shall be a defect at the solution station.
- AC7: A component whose parent has no design file shall be an error.
