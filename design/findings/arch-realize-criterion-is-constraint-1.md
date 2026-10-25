---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.realize
digest: fbc20c97d98a
evidence: No component outside realize shall depend on a language adapter.
hint: Make it a constraint scoped to every component outside arch.realize that forbids depending on language adapters, and remove it from the criteria.
---
This limits what other components may import, not what realize does. It binds parts that never read this file.
