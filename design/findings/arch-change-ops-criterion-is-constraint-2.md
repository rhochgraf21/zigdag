---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.change.ops
digest: b2cd7e3f69cc
evidence: Each operation shall change the design only through the Draft protocol defined here
hint: "Record it as a decision on this part (Chose: operations edit only through a Draft protocol; Over: operations writing files directly) or as a constraint, and drop AC5 from the criteria."
---
AC5 limits how operations are built (which interface they may use to touch the design) rather than stating anything they do. Written as a criterion, this structural rule is hidden from arch.change.apply, which has to supply the Draft.
