---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.change.ops
digest: "72b6f8001b7f"
evidence: Each operation shall apply itself to a Draft protocol defined here
hint: Remove AC5 and record the Draft protocol as a decision or as code. If the boundary matters, state it as a constraint or a `uses` rule.
---
This fixes an internal interface and keeps file and transaction handling out of operations, which limits how the part is built rather than what it does. It also contradicts the root decision that interfaces live in code, not in design files.
