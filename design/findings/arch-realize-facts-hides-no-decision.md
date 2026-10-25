---
kind: question
station: solution
source: critic
by: hides-no-decision
subject: arch.realize.facts
digest: b1d7ed838a67
evidence: Fact representation and comparison
hint: Say that the fact schema is a visible design rule and hides nothing, or name a decision that can change without touching adapters, such as how interface changes are classified.
---
The rationale calls the fact schema the design rule that adapters and core both build against, so its representation is visible to every other part, not a secret. A part whose interface is the representation cannot hide it.
