---
kind: component
realizes: Lead actors through structured design reasoning and toward the most valuable next work
solution: Deterministic advisors (next actions, work plans, brownfield inference) plus tool-agnostic method documents for elicitation, statement critique, zigzag decomposition, contradiction resolution and review
hides: Prioritization heuristics and method content
serves: [sound-reasoning, low-adoption-cost, compose-at-scale]
uses: [model, realize, check, change]
exports: [method, next, plan, infer]
status: specified
---
## Acceptance criteria
- AC1: Every advisor shall return proposals as data (operations or ranked items) and shall never modify the design itself.
- AC2: Method documents shall refer to abstract operations in model terms ("the context of a component"), never to commands.

## Rationale
AC2 is what keeps guide independent of integrate (see guide.method's decisions).
