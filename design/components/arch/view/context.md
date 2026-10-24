---
kind: component
realizes: Give an actor the minimal sufficient knowledge to work on a component or a source location
solution: A context card holding the chain up to needs, realizes/solution/hides, acceptance criteria with evidence status, port signatures and contracts, effective constraints, allowed uses described only by their external specs, and open findings, trimmed by priority to a size budget
hides: Selection and truncation policy
uses: [model.graph, realize.facts, realize.mapping, check.engine]
status: specified
---
## Acceptance criteria
- AC1: Given a source path or path:line, the card shall be for the component that unit maps to, and shall include its chain to needs.
- AC2: Neighbouring components shall appear only as their external spec (realizes, port signatures, contracts), never their internals.
- AC3: When over budget, sections shall be dropped in a fixed priority order and the omission stated in the card.
- AC4: The card for a component with at most 10 port symbols and 5 uses shall fit in 4k tokens, estimated as characters divided by 4.

## Rationale
Resolves X02 (context completeness against context size) through information hiding: the card is
complete about *this* component and deliberately shallow about everything else.
