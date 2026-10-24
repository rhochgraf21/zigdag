---
kind: component
realizes: Define the node kinds, their fields, and what makes an individual node valid
solution: Frozen dataclasses and enums per kind (Need, Component, Constraint, Decision) with distinct id types, and a JSON Schema generated from them for editors and agents
hides: Field representation and per-field validation
uses: []
status: specified
---
## Acceptance criteria
- AC1: The schema shall define exactly four node kinds; adding a kind requires a decision record.
- AC2: When a node has an unknown field, lacks a required field, or has a malformed reference, validation shall return an issue naming the field, and shall not raise (check.engine turns issues into findings).
- AC3: The published JSON Schema shall be generated from the types, never written by hand.
- AC4: Acceptance criteria shall be parsed from `- ACn:` lines in the component body, each with a stable id `<component>#ACn`.

## Rationale
Ids are distinct domain types (ComponentId, NeedId, ConstraintId, DecisionId), so a need can never be
passed where a component is expected. A Hypothesis strategy is registered per type and reused by
every property test in arch.

## Alternatives rejected
- pydantic: a heavy runtime dependency with its own coercion semantics; we want strict, inert values.
- Plain dicts: primitive obsession; every consumer would re-validate.
