---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch
digest: f01c19fd1f95
evidence: arch's own design shall be maintained with arch
hint: Make dogfooding a constraint on the repository (its design must pass `arch check` with an empty baseline in CI) and drop it from the acceptance criteria.
---
This limits the tools used to develop arch, not what arch does for its users. "Maintained with arch" also describes a process that no test of the product can decide.
