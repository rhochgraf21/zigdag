---
kind: component
realizes: Detect where the realization departs from the design
solution: Rules that compare facts about the code with the design and report each departure
hides: Comparison rules
uses: [engine, model.graph, model.ids, model.policy, model.schema, realize.facts, realize.mapping]
status: specified
---
## Acceptance criteria
- AC1: An import from a unit in component a to a unit in component b shall be a finding unless a and b are the same component, b is inside a, or may_use(a, b) holds.
- AC2: When an effect falls outside a component's allowance, conformance shall report an error.
- AC9: A criterion whose linked test failed or errored in a test report shall be an error naming the test and the report.
- AC8: A direct effect shall be an error when a `direct_effects` rule applies and does not grant that effect to the component or one of its ancestors.
- AC3: An acceptance criterion without a linked contract or test shall be info below status contracted and an error at or above it.
- AC4: Each finding shall name both the design element and the source location.
- AC5: When a rule needs a capability the unit's adapter did not analyze, it shall report "not analyzed" at info level and shall never pass silently.
- AC6: A design link naming an unknown component or acceptance criterion shall be an error at the link's location.
- AC7: Components without code shall be reported once per unbuilt subtree, at info below status contracted and as an error at or above it.
- AC10: When a public port of a component under a port_types rule exposes a forbidden built-in at a leaf position, conformance shall report an error (bool returns aside where allowed), and an unannotated port parameter as a warning.
- AC11: When a function declares its side effects with deal (has or pure), conformance shall report each inferred effect that no declared marker covers as an error, and dynamic code as a warning.
- AC12: When a component's code has surviving mutants, conformance shall report how many survived and in which functions: an error at status verified, a warning at contracted, info below.
- AC13: When an effect cannot be known in a component under an effect constraint, conformance shall report a warning.
- AC14: When an interface name needs a description and has none, conformance shall report it, with a severity that rises as the component matures.
- AC15: When a description only repeats its name and type, conformance shall report it.

## Decisions
### Describe interface names, not local variables
- Chose: require a one-line description only for exported names that their name and type do not explain, and show locals by the line that set them
- Over: a description for every variable and function
- Because: a description pays when it is read at many use sites, and a local is read once, a few lines below where it is set. Comments on locals mostly restate the name, drift unchecked and teach readers to skip comments
- Consequences: 205 of arch's 565 public fields need no description because their type says it. Ambiguous names such as before and after should often be renamed rather than described
