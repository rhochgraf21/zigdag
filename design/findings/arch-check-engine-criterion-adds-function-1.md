---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.check.engine
digest: db512fefae48
evidence: If a finding does not come from a rule, then it shall not fail a check on its own.
hint: Name severity grading for all findings in a requirement, either in a part that owns the parent's 'one rule for severity' or by widening the engine's realizes, and move AC2 and AC4 there.
---
The requirement covers evaluating rules, but this criterion grades findings from critics, people and agents that the engine never produces. Deciding severity for every finding, whatever its source (AC2 points the same way), is a second function that has no requirement of its own.
