---
kind: question
station: requirements
source: critic
by: constraint-is-function
subject: agent-neutral
digest: "6ea62e8ab214"
evidence: with a generic fallback that works for any agent
hint: Keep the constraint to the limit (no language model calls, and product-specific code only in adapters under arch.integrate.agent). Make the generic fallback a requirement or criterion of arch.integrate.agent.
---
Requiring a generic fallback that works for any agent asks some part to provide a capability, which makes it a function rather than a limit on every solution. Left inside a constraint, that function has no owner and no criteria of its own.
