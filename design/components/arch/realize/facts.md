---
kind: component
realizes: Represent what is true of the realization in a language-neutral form
solution: Typed records of what the code contains and does, the snapshot they come from, and the adapter protocol
hides: Fact representation and comparison
uses: []
status: specified
---
## Acceptance criteria
- AC1: Every fact shall carry a source location (path and line).
- AC2: diff(before, after) shall report added, removed and changed port signatures and contracts, classified as breaking, compatible, or needs-review (any change to a contract expression).
- AC3: EffectUse facts shall distinguish direct uses from transitive ones.
- AC4: The fact schema shall have no language-specific fields.
- AC5: Every unit shall record its language and the capabilities its adapter analyzed (structure, api, contracts, effects, links), so consumers can tell "absent" from "not analyzed".
- AC6: Unit names shall be dotted segments defined by each adapter, so imports may cross languages (for example Mojo importing a Python module).
- AC7: The fact schema shall depend on no other arch component, so an adapter needs only this module.
- AC8: Facts shall record every definition, public or private, with its lines and its one-line description.
- AC9: Facts shall record each call site with the lines that the call spans.
- AC10: An interface name shall need a description when its name and type do not explain it and it inherits none from a base method.

## Rationale
This is arch's most important internal design rule in the Baldwin and Clark sense: adapters and core
evolve independently as long as it holds still. Changing it requires a decision entry here.
