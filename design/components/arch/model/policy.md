---
kind: component
realizes: Say what the constraints in force require of each component
solution: One typed rule per kind of constraint, which parses itself, combines with others and says what it permits
hides: The rule syntax written in constraint files
uses: [ids]
status: specified
---
## Acceptance criteria
- AC1: A constraint's rule shall parse into a typed policy.
- AC2: Combining policies shall only tighten: forbidden effects accumulate and allow-lists intersect.
- AC3: Each rule kind shall answer its own question (is this effect permitted here, is this package allowed for this component), so checks never interpret raw rule data.
- AC4: If a rule is unknown or malformed, then the policy shall report a problem instead of failing.
- AC5: Where a constraint requires critique, the policy shall require it for every component in the constraint's scope.

## Decisions
### Checks ask the policy, not the file
- Chose: typed policies with behavior (`verdict`, `permits`, `allows`), combined by the graph into an effective policy per component.
- Over: storing the rule as JSON and letting each check interpret it.
- Because: interpretation in several checks drifts apart, and malformed rules would only surface when some check happened to read them.
- Consequences: a malformed rule is reported when the design loads.
- Previously: rules were kept as canonical JSON and parsed inside `check.conformance`.
