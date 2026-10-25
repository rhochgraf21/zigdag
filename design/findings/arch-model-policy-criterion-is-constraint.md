---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.model.policy
digest: "866dcaae241e"
evidence: so checks never interpret raw rule data
hint: Remove the clause from AC3, keeping the policy's observable answers, and state 'checks read rules only through the policy' as a constraint scoped to the check components.
---
This clause sets a rule for how other components, the checks, may be built. It says nothing about what the policy does, so the checks it binds will never see it among their own requirements.
