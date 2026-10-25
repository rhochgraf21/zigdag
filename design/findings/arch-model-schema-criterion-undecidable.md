---
kind: question
station: requirements
source: critic
by: criterion-undecidable
subject: arch.model.schema
digest: "7bee977f488e"
evidence: Adding a node kind shall require a decision entry on this component.
hint: Drop it, since AC1 already fails when a kind is added, or turn it into a constraint that a check enforces on changes to node kinds.
---
No test of the schema can pass or fail this. It is a rule about how people later change the design, not about what the schema does, so it gives no evidence about the part.
