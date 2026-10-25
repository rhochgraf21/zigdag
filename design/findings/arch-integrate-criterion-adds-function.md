---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.integrate
digest: d428a62ca9d4
evidence: it shall write a draft design
hint: Give bootstrapping a design its own requirement and child component (or move it to the part that infers designs), and keep AC3 to the observable workflow outcome, e.g. that `arch init` followed by `arch check` succeeds on a fresh project.
---
Writing a draft design for a project that has none is a function of its own (deriving a design from existing code), not a trigger, condition or output of making arch available inside existing workflows. Here it has no solution or owner of its own.
