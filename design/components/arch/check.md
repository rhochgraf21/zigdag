---
kind: component
realizes: Determine whether the design is well formed and whether the realization conforms to it
solution: A rule engine over the design and facts, with deterministic statement, structure and conformance rule sets and a baseline ratchet
hides: Rule evaluation and finding identity
serves: [catch-departures, sound-reasoning, trace-purpose, compose-at-scale]
uses: [model, realize]
exports: [engine]
status: specified
---
## Acceptance criteria
- AC1: Every finding shall name a rule id, a subject (node id or source location), a severity (error, warning, info) and a one-line fix hint.
- AC2: When scoped to a component, only that subtree and the external specs it uses shall be evaluated.
- AC3: Findings recorded in the baseline shall never signal failure.
- AC4: Results shall not depend on the order in which rules run.
- AC5: Strictness shall scale with maturity: a rule may set a lower severity for components at status draft or specified.
