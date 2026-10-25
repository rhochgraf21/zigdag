---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.integrate.catalog
digest: fc56099ac5e8
evidence: Only the surfaces shall parse text into domain types.
hint: Make it a constraint scoped to arch or integrate, so every component inherits it, and remove it from the catalog's criteria.
---
This limits how every other part may be built, since none but the surfaces may parse text, rather than saying what the catalog does. As a catalog criterion it is hidden from the parts it binds.
