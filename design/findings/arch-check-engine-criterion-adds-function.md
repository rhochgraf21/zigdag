---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.check.engine
digest: f2917bba84a0
evidence: If a finding does not come from a rule, then it shall not fail a check on its own.
hint: Widen the requirement to name it (for example, "... producing findings with stable identities, and grade every finding's severity under one rule"), or give severity its own component.
---
The requirement is to evaluate rules, but this criterion governs findings that no rule produced, from critics, people and agents. Grading every finding's severity is the parent's "one rule for severity", a function this requirement does not name.
