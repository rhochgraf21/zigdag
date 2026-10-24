---
kind: component
realizes: Detect where the realization departs from the design
solution: Rules comparing mapped facts with the design for undeclared or invisible imports, effects outside the effective allowance, unmapped units, missing code, acceptance criteria without evidence, failing or stale evidence, budget breaches and dependencies outside the allowlist
hides: Comparison rules
uses: [engine, model.graph, model.ids, model.policy, realize.facts, realize.mapping]
status: specified
---
## Acceptance criteria
- AC1: An import from a unit in component a to a unit in component b shall be a finding unless a and b are the same component, b is inside a, or may_use(a, b) holds.
- AC2: An effect fact outside the component's effective allowance shall be an error; an `unknown` effect in a component under any effect constraint shall be a warning.
- AC9: A criterion whose linked test failed or errored in a test report shall be an error naming the test and the report.
- AC8: A direct effect shall be an error when a `direct_effects` rule applies and does not grant that effect to the component or one of its ancestors.
- AC3: An acceptance criterion without a linked contract or test shall be info below status contracted and an error at or above it.
- AC4: Each finding shall name both the design element and the source location.
- AC5: When a rule needs a capability the unit's adapter did not analyze, it shall report "not analyzed" at info level and shall never pass silently.
- AC6: A design link naming an unknown component or acceptance criterion shall be an error at the link's location.
- AC7: Components without code shall be reported once per unbuilt subtree, at info below status contracted and as an error at or above it.
