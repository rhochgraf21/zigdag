---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.change
digest: "54197db5cd22"
evidence: The diff between two design states shall be computable from their files alone
hint: Either add the function to the requirement (for example, "Change the design through validated operations, and show what any change did") or move the diff to a sibling that owns reviewable differences.
---
Computing a diff between any two design states is a separate function from changing the design. It already has its own child requirement (arch.change.diff), which shows that the parent requirement does not name it.
