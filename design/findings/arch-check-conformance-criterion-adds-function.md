---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.check.conformance
digest: "52cfc0d26fa4"
evidence: When a component's code has surviving mutants
hint: Move this to a part whose requirement is judging how strong the evidence is, or widen the requirement to cover the evidence behind each criterion as well as departures.
---
Surviving mutants measure how strong the tests are, not where the code departs from the design. This adds a mutation-testing assessment that the requirement does not name and that the solution's comparison rules do not cover.
