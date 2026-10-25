---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch
digest: f01c19fd1f95
evidence: arch shall never require network access, an account, or a particular coding agent.
hint: Remove AC4 and rely on the no-network and agent-neutral constraints, adding the account clause to no-network if it is not already there.
---
This limits how every part may be built (no network, no account, no agent lock-in), not what arch does. The decisions already cite the no-network and agent-neutral constraints, so the criterion repeats them where other parts will not see it.
