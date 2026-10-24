---
kind: component
realizes: Describe how to reason well at each design step, independent of any tool surface
solution: Written methods for eliciting needs, writing requirements, decomposing, resolving coupling and reviewing design changes
hides: Method content
uses: [model.ids, model.schema]
status: specified
---
## Acceptance criteria
- AC1: Each method shall state its inputs, steps, exit criteria and the abstract operations it uses.
- AC2: Each method shall end with a self-check against arch's deterministic rules before anything is proposed.
- AC3: Each method shall ship at least one worked example whose result passes `arch check`.

## Rationale
This is where "structured thinking makes agents act like experts" lives. The deterministic rules are
the method's exit gate, so the judgement step cannot quietly skip the discipline.

## Decisions
### Method content separate from skill packaging
- Chose: methods written against abstract operations here; `integrate.agent` renders them into product-specific skills with real commands from the catalog.
- Over: skills with concrete commands kept in `guide`.
- Because: skills name commands, so any rename in `integrate.catalog` would break them; guide's requirement would depend on a later design parameter (TRIZ: separation by system level).
- Consequences: methods can be tested by worked examples without any agent product.
- Previously: skills lived in `guide`; split when the matrix showed the backward dependency.
