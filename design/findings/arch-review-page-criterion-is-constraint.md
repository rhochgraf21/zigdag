---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.review.page
digest: "3141ae1ada77"
evidence: The page shall load no external resources.
hint: Record it as a constraint (for example 'Review and site pages load no external resources') applied to the parts it binds, and remove it from the criteria.
---
This limits how the page may be built (its network use), not what it does for the reviewer. As a criterion it hides from other parts it binds, such as arch.view.site, which repeats the same limit.
