---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.realize.facts
digest: b1d7ed838a67
evidence: The fact schema shall depend on no other arch component
hint: "Drop it and rely on `uses: []`, or make it a constraint scoped to arch.realize.facts."
---
This limits what the part may import, not what it does. `uses: []` already declares it, so the criterion repeats a structural rule.
