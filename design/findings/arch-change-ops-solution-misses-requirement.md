---
kind: question
station: solution
source: critic
by: solution-misses-requirement
subject: arch.change.ops
digest: c378fcc6c5eb
evidence: checked against a published schema
hint: Say in the solution that each operation checks its preconditions against the current design before it edits, e.g. '... checked against a published schema, each checking its preconditions against the draft design before it edits'.
---
The requirement asks for operations with preconditions, but the solution only says they are checked against a schema. A schema checks an operation's form, not whether it may apply to the current design, so the refusals in AC3 and AC7 are not covered by the solution.
