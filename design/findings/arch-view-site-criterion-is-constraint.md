---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.view.site
digest: "9d9c1ecfd3af"
evidence: The site shall work from the local filesystem with no network access.
hint: Record one constraint (for example 'Generated pages work offline and load no external resources') applied to the site and the review page, and drop AC1 and AC3 here.
---
This limits how the site may be built (its network and hosting), not what it does for the reader, and arch.review.page carries the same limit as its own criterion. As separate criteria the shared limit is hidden from the parts it binds.
