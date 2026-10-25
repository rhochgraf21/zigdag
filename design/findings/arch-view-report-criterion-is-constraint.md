---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.view.report
digest: "59d2cbda354b"
evidence: compute nothing itself
hint: Move 'reports compute nothing' to a constraint or to the decision 'Results are model objects that render themselves', and keep AC1 to 'Each report shall render as Markdown and as JSON with the same content.'
---
This limits how the report part may be built, not what it does, and no output test can tell whether a report computed something. It belongs with the rule about where results are computed.
