---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.review.explain
digest: "4101ab3ae6db"
evidence: the change shall ask whether the description is still true
hint: Move the stale-description prompt to a requirement that owns documentation checks, or name that function in this part's realizes if it really belongs here.
---
Asking the reviewer to confirm a possibly stale description is a documentation check, not a reason for the change or the meaning of a name. It adds a function that the requirement does not name and that has no solution of its own.
