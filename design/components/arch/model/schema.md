---
kind: component
realizes: Define the node kinds, their fields, and what makes an individual node valid
solution: Frozen dataclasses and enums per kind (Need, Component, Constraint) with distinct id types, and a JSON Schema generated from them for editors and agents
hides: Field representation and per-field validation
uses: [ids, policy]
status: specified
---
## Acceptance criteria
- AC1: The schema shall define exactly three node kinds (need, component, constraint); adding one requires a decision entry on this component.
- AC2: When a node has an unknown field, lacks a required field, or has a malformed reference, validation shall return an issue naming the field, and shall not raise (check.engine turns issues into findings).
- AC3: The published JSON Schema shall be generated from the types, never written by hand.
- AC4: Acceptance criteria shall be parsed from `- ACn:` lines in the component body, each with a stable id `<component>#ACn`.
- AC5: A component's `## Decisions` section shall be parsed into entries (title, text, labels, location), one per `### title`.

## Rationale
Ids are distinct domain types (ComponentId, NeedId, ConstraintId), so a need can never be
passed where a component is expected. A Hypothesis strategy is registered per type and reused by
every property test in arch.

## Decisions
### One component node per FR/DP pair
- Chose: a single Component node holding the FR (`realizes`), its DP (`solution`) and the DP's secret (`hides`), with design-matrix entries in `uses`.
- Over: separate FR and DP nodes, as axiomatic design draws them.
- Because: in an ideal design they pair one to one, so separate nodes would double the files and the indirection.
- Consequences: an FR met jointly by several DPs must be split into several FRs, which axiomatic design recommends anyway.

### Decisions live on components, not as nodes
- Chose: a `## Decisions` section on the component whose DP embodies the choice (system-wide ones on the root), and `accepts_coupling` on a parent for couplings kept on purpose.
- Over: a separate decision kind (ADR-style records linked to components by `affects`).
- Because: in axiomatic design a decision is the choice of a DP, so its reasoning belongs with that DP. Separate records duplicated component rationale and depended on hand-kept links that nothing could verify as complete.
- Consequences: three node kinds; decisions appear wherever their component does; a chronological log can be generated from git history.
- Previously: a fourth node kind holding 14 records; folded in because 8 of them were already repeated in their components.

### Frozen dataclasses for nodes
- Chose: frozen dataclasses, enums and NewType ids.
- Over: pydantic; plain dicts.
- Because: pydantic is a heavy runtime dependency with its own coercion semantics, where we want strict, inert values; plain dicts are primitive obsession that every consumer would re-validate.
