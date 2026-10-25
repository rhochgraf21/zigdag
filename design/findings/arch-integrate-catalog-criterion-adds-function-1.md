---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.integrate.catalog
digest: e0436f837702
evidence: "`arch init` shall write the inferred design and a baseline of whatever errors remain"
hint: Move the init behaviour to the component that owns adoption (e.g. a child or sibling that realizes 'Start an existing project with a passing check'), and keep catalog criteria about how operations are declared and run.
---
AC8 requires a new function, setting up a project with an inferred design and a baseline. The requirement only asks to define every operation once with typed inputs and outputs. Adoption has no requirement or solution of its own here.
