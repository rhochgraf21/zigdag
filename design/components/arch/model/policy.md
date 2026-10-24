---
kind: component
realizes: Represent what constraints require as typed policies, and combine the policies in force for a component
solution: One frozen type per rule kind (effects, direct effects, imports, port types, budget), each able to parse itself, combine with others and answer what it permits; a Policy holding all of them
hides: The rule syntax written in constraint files
uses: [ids]
status: specified
---
## Acceptance criteria
- AC1: A constraint's rule shall parse into a typed Policy; unknown rules, unknown effect names and malformed values shall be reported as problems, never raised.
- AC2: Combining policies shall only tighten: forbidden effects accumulate and allow-lists intersect.
- AC3: Each rule kind shall answer its own question (is this effect permitted here, is this package allowed for this component), so checks never interpret raw rule data.

## Decisions
### Checks ask the policy, not the file
- Chose: typed policies with behavior (`verdict`, `permits`, `allows`), combined by the graph into an effective policy per component.
- Over: storing the rule as JSON and letting each check interpret it.
- Because: interpretation in several checks drifts apart, and malformed rules would only surface when some check happened to read them.
- Consequences: a malformed rule is reported when the design loads.
- Previously: rules were kept as canonical JSON and parsed inside `check.conformance`.
