---
kind: question
station: requirements
source: critic
by: requirement-not-from-parent
subject: arch.realize.history
digest: e711d701293a
evidence: Extract change history, meaning churn per unit and units that change together
hint: Add reading version-control history to arch.realize's solution (it already hides version control), or place this component under the part that needs churn and co-change.
---
Nothing in the parent's solution (facts from source snapshots, a mapping, scaffolding) needs churn or co-change, and a version-control log is not a source snapshot. So this requirement does not follow from the parent's choice.
