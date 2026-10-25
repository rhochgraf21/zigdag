---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.realize.history
digest: e711d701293a
evidence: When given unified diff output, history shall produce each file's change
hint: Give diff parsing its own requirement and component, placed where code hunks are needed, and keep history to churn and co-change.
---
Parsing unified diffs into hunks is a function the requirement (churn and co-change) does not name. The solution, a `git log --numstat` parser, does not provide it either.
