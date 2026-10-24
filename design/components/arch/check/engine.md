---
kind: component
realizes: Evaluate rules over a design and facts, producing findings with stable identities
solution: Rules are pure functions registered with an id, a scope and a default severity; a finding's identity is (rule id, subject id, normalized message key) and excludes line numbers
hides: Rule scheduling, scoping and identity computation
uses: [model.graph, model.ids, model.schema, realize.facts]
status: specified
---
## Acceptance criteria
- AC1: A finding's identity shall not change when unrelated lines in the same file move.
- AC2: Severity shall be overridable per rule and per subtree in project configuration.
- AC3: When a rule raises, it shall produce an internal-error finding for that rule and the other rules shall still run.
