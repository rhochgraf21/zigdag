---
kind: component
realizes: Give an actor the minimal sufficient knowledge to work on a component or a source location
solution: A card with the component's purpose, interface, rules, criteria and neighbours, trimmed to a size budget
hides: Selection and truncation policy
uses: [render, model.graph, model.ids, model.matrix, realize.facts, realize.mapping, check.engine]
status: specified
---
## Acceptance criteria
- AC1: Given a source path or path:line, the card shall be for the component that unit maps to, and shall include its chain to needs.
- AC2: Neighbouring components shall appear only as their external spec (realizes, port signatures, contracts), never their internals.
- AC3: When over budget, sections shall be dropped in a fixed priority order and the omission stated in the card.
- AC4: The card for a component with at most 10 port symbols and 5 uses shall fit in 4k tokens, estimated as characters divided by 4.
- AC5: A component's card shall say how many files outside it import its code, and in how many components.

## Decisions
### Neighbours by external spec only
- Chose: complete about the component being worked on; neighbours only as realizes, port signatures and contracts.
- Over: including neighbours' internals, or leaving neighbours out.
- Because: more complete context means fewer wrong guesses but costs size and attention. Neighbours' internals are hidden by design, so leaving them out is correct rather than lossy (TRIZ: separation by system level; information hiding).
