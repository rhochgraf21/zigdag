---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.guide.infer
digest: "796b1a916768"
evidence: a baseline of whatever errors remain
hint: Give the baseline and the `arch init` behaviour to the part that owns baselines or the init command, and limit this criterion to what infer emits, such as the draft operations.
---
AC5 adds a second function, recording a baseline of the remaining errors so that checks pass, which is not drafting a decomposition. Baselining then has no design parameter of its own in this part.
