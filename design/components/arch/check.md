---
kind: component
realizes: Judge the quality of the design and of the code that realizes it
solution: Deterministic rule sets, findings from critics, people and agents, and a ledger of answers, under one rule for severity
hides: Rule evaluation and finding identity
serves: [catch-departures, sound-reasoning, trace-purpose, compose-at-scale]
uses: [model, realize]
exports: [engine, ledger, promotion]
status: specified
---
## Acceptance criteria
- AC1: Every finding shall name its detector, its subject, its station, its kind and a one-line fix hint.
- AC2: When scoped to a component, only that subtree and the external specs it uses shall be evaluated.
- AC3: When a finding has an answer, it shall never signal failure.
- AC4: Results shall not depend on the order in which rules run.
- AC5: A defect from a rule shall block only at a station its subject's status claims, and always at the form and code stations.

## Decisions
### Strict checks that don't block adoption
- Chose: a baseline ratchet (existing findings never block, new ones do, fixed ones cannot return) and severity that scales with maturity, with `guide.infer` starting existing code green.
- Over: one strictness for every component from day one.
- Because: stricter checks catch more departures but make adoption on existing code a wall of red (TRIZ: separation in time, and by condition).
