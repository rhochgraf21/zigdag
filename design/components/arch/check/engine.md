---
kind: component
realizes: Evaluate rules over a design and facts, producing findings with stable identities and severities
solution: Rules as pure functions with an id, a scope and a default severity, producing findings whose identity ignores line numbers
hides: How a finding's identity is computed
publishes: "The finding model: stations, kinds, sources and the one rule for severity"
uses: [model.graph, model.ids, model.schema, realize.facts]
status: specified
---
## Acceptance criteria
- AC1: A finding's identity shall not change when unrelated lines in the same file move.
- AC2: The engine shall derive a finding's severity from its station, its kind, its source and how far its subject has come.
- AC3: When a rule raises, it shall produce an internal-error finding for that rule and the other rules shall still run.
- AC4: If a finding does not come from a rule, then it shall not fail a check on its own.
