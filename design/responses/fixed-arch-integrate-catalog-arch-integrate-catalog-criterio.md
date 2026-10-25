---
answer: fixed
by: robert
findings:
  - {rule: criterion-adds-function, subject: arch.integrate.catalog, key: arch-integrate-catalog-criterion-adds-function-1}
---
Moved the init criterion to arch.integrate (AC3), which serves low adoption cost and holds both the workspace that writes and the catalog that orchestrates; the catalog keeps criteria about how operations are declared and run.
