---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.check.conformance
digest: "13b298d42be4"
evidence: When an interface name needs a description and has none
hint: Create a code-quality sibling under check, for example 'Judge how readable the code's interfaces are', and move AC14, AC15 and the 'Describe interface names' decision to it.
---
Whether exported names carry descriptions is documentation quality, not a departure from the design. This criterion, and AC15 with it, gives conformance a function its requirement does not name, and no sibling owns it either.
