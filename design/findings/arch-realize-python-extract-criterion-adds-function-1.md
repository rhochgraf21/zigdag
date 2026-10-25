---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.realize.python.extract
digest: "7e0516c27576"
evidence: Names in code shall resolve to their definitions through imports, typed parameters and self.
hint: Add reference resolution to realizes (e.g. '... and the definitions that names refer to'), or move names() and AC8/AC10 to a part that owns name resolution for review explanations.
---
AC8, served by the public names() function, requires resolving name references to their definitions. That function is not among the facts the requirement lists (units, imports, public API, ports, contracts, effect uses, design links), so it has no requirement of its own here.
