---
kind: component
realizes: Detect defective need and requirement statements
solution: Word lists and patterns that flag defective needs and requirements, extensible per project, with suppressions recorded on the node
hides: Lexicons and patterns
uses: [engine, model.ids]
status: specified
---
## Acceptance criteria
- AC1: Each finding shall quote the offending phrase and name the pattern to use instead.
- AC2: Lexicons shall be extensible per project.
- AC3: A suppression shall be recorded on the node with a reason, and a suppression without a reason shall itself be a finding.

## Rationale
Deterministic rules catch the common failures cheaply on every run. Nuanced critique ("is this a need
or a disguised solution?") is a method in `guide.method`, run by the user's agent when it is worth it (the root's decision: no language model inside arch).
