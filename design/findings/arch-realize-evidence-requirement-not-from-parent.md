---
kind: question
station: requirements
source: critic
by: requirement-not-from-parent
subject: arch.realize.evidence
digest: "67916962e4a4"
evidence: Extract verification results from reports produced by other tools
hint: Add reading verification reports to arch.realize's solution (it already hides report formats), or move this component under the part whose solution needs evidence.
---
The parent's solution names facts extracted from source snapshots by adapters, a mapping, and scaffolding. Reading test, coverage and mutation reports is none of these, so this requirement does not follow from the parent's choice and the parent's solution is incomplete.
