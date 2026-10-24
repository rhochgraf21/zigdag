---
kind: component
realizes: Describe how to reason well at each design step, independent of any tool surface
solution: Method documents for eliciting needs, writing solution-neutral needs and EARS requirements, zigzag decomposition with Parnas secrets, resolving coupling with TRIZ separation principles and ASIT closed-world and unification, and reviewing a design diff
hides: Method content
uses: []
status: specified
---
## Acceptance criteria
- AC1: Each method shall state its inputs, steps, exit criteria and the abstract operations it uses.
- AC2: Each method shall end with a self-check against arch's deterministic rules before anything is proposed.
- AC3: Each method shall ship at least one worked example whose result passes `arch check`.

## Rationale
This is where "structured thinking makes agents act like experts" lives. The deterministic rules are
the method's exit gate, so the judgement step cannot quietly skip the discipline.
