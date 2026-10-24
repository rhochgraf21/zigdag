---
kind: component
realizes: Determine which component each source unit belongs to
solution: Longest-prefix match of each unit's module path against component code paths, where a component's code path defaults to its id
hides: Resolution rules
uses: [facts, model.graph, model.schema]
status: specified
---
## Acceptance criteria
- AC1: Each unit shall map to at most one component: the one whose code path is the longest prefix of the unit's module path.
- AC2: Units matching no component shall be reported as unmapped, never assigned silently.
- AC3: Two components with the same code path shall be a finding.
- AC4: Units under test roots shall be treated as evidence: never mapped to a component and never reported as unmapped.
- AC5: An import target shall resolve to the longest dotted prefix that names a project unit, so `from pkg import mod` and `from pkg.mod import name` both resolve to `pkg.mod`.
