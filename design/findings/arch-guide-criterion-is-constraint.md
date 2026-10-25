---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.guide
digest: ac2e68186183
evidence: Method documents shall refer to abstract operations in model terms
hint: Express it as a constraint or a `uses` rule (guide shall not depend on integrate, and method documents name no commands) and drop AC2.
---
The rationale says this criterion exists to keep guide independent of integrate, so it is a dependency limit on how guide is built, not something guide does. Written as a criterion, it is hidden from integrate and any other part it binds.
