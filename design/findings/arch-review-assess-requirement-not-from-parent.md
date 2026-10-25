---
kind: question
station: requirements
source: critic
by: requirement-not-from-parent
subject: arch.review.assess
digest: "4586b89b0597"
evidence: Judge how risky each changed file is
hint: Add risk to arch.review's solution (for example 'pages weighted by each file's risk and evidence') so this part follows from it.
---
The parent's solution is review pages built from the diffs, with verdicts kept per page. Nothing in it needs a risk score, so this requirement comes from the proportional-review need rather than from the parent's design choice, and the parent's solution is incomplete.
