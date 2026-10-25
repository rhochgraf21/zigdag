---
kind: question
station: solution
source: critic
by: solution-misses-requirement
subject: arch.integrate.catalog
digest: a50596b7d0cc
evidence: each run the same way by the CLI, the MCP server and agent hooks
hint: Either let integrate.agent register its operations with the catalog (the catalog holds the registry without depending on the adapter), or narrow realizes and the solution so they name the agent commands as an exception.
---
arch.integrate.agent records that `arch agent install` and `arch hook` are served by the adapter and called directly by the CLI, not through the catalog. So the registry does not hold every user-facing operation, and hooks do not run through it.
