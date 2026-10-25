---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch
digest: ad6161dae3ff
evidence: arch shall produce a dependency map, a design structure matrix, hotspots and a draft decomposition
hint: Make analysing an undesigned codebase its own requirement with its own solution, or add it to realizes as a deliberate second function, and keep AC1 on the child that owns it.
---
The requirement is to keep a checked model of intent and structure. Analysing a codebase that has no design yet, and producing dependency maps and hotspots from it, is a separate function, and the solution does not cover it.
