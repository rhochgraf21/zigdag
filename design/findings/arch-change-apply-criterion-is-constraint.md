---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.change.apply
digest: "83bf5af3886b"
evidence: apply shall be a pure function
hint: "Rely on the pure-core constraint and restate AC1 as observable behaviour, for example: the same design, facts and operations shall always yield the same new design, edits and findings."
---
Requiring a pure function limits how apply is implemented, not what result it produces. The pure-core constraint already imposes this on every part.
