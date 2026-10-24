---
kind: decision
status: accepted
affects: [arch, arch.check.statements, arch.guide.method]
---
## Context
Some design work is mechanical (graph integrity, boundaries, effects); some is judgement (is this need
solution-neutral? which decomposition is better?). arch could call a model for the judgement part.

## Decision
arch never calls a language model. Deterministic rules live in `check`; judgement lives in `guide.method`
procedures that the user's own agent runs, ending in arch's deterministic self-check.

## Consequences
arch stays offline, reproducible, cheap and agent-neutral. Its judgement quality improves as agents
improve, without arch changing. Cost: no built-in "critique" command for users who run arch with no agent.
