---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.realize.facts
digest: b1d7ed838a67
evidence: diff(before, after) shall report added, removed and changed port signatures and contracts
hint: Give interface-change classification its own requirement and component, for example 'Classify interface changes between two snapshots', which uses facts.
---
The requirement is to represent what is true of the realization. It does not name comparing two snapshots and judging changes as breaking or compatible, so that function has no design parameter of its own.
