---
kind: component
realizes: Detect structural defects in the design
solution: Graph rules for dangling references, components with no path to a need, needs served by nothing, more than nine children, coupled sibling sets, stale accepted couplings, missing secrets, decision entries without a choice or reason, children whose uses exceed their parent's, constraints loosened by descendants, and child budgets exceeding the parent's
hides: The structural rule set
uses: [engine, model.graph, model.matrix, model.schema]
status: specified
---
## Acceptance criteria
- AC1: A coupled sibling set shall be an error, or a warning when the parent's `accepts_coupling` names all its members.
- AC2: A component with more than nine children shall be a warning.
- AC3: A non-root component without `hides` shall be a warning at status specified and an error at contracted or above.
- AC4: A child whose uses reach outside its siblings shall be an error unless its parent may use the target.
- AC5: An `accepts_coupling` entry whose members are no longer coupled shall be a warning.
- AC6: A decision entry without `Chose:` and `Because:` lines shall be a warning.
