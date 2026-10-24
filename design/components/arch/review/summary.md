---
kind: component
realizes: Let a reviewer judge a change with effort proportional to its risk
solution: A layered Markdown summary (intent, design, structure with a change diagram, port changes classified for callers, evidence, then changed files ranked by a documented risk score), each layer collapsible, sized for a pull-request comment
hides: Layering and risk scoring
uses: [change.diff, realize.facts, check.engine, view.diagram, view.render, model.graph, model.ids, model.schema, realize.history, realize.mapping, assess]
status: specified
---
## Acceptance criteria
- AC1: Layers shall appear in a fixed order (intent, design, structure, contracts, evidence, code), each collapsible.
- AC2: Each changed source file shall be ranked by a documented score combining whether it touches a port, crosses a boundary, the component's maturity, its evidence status, and its hotspot score.
- AC3: Changes inside components at status verified, with passing linked evidence and no port change, shall be listed as low risk and collapsed.
- AC4: The summary shall fit in 65,000 characters, trimming code-layer detail first.
