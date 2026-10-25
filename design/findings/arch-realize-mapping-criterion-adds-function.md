---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.realize.mapping
digest: a54393cb0646
evidence: An import target shall resolve to the longest dotted prefix that names a project unit
hint: Move import resolution to the extractors (python.extract already resolves relative imports) or to its own part, and keep mapping to assigning units to components.
---
Resolving an import to a project unit is a function the requirement does not name. Mapping assigns units to components, while import resolution decides which unit an import refers to.
