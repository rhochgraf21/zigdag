---
kind: component
realizes: Have design text judged by an independent critic against a rubric
solution: A rubric as data, requests that give a critic only the text and its context, and answers kept only where the critic quotes the text
hides: The rubric's questions and how answers are judged
uses: [engine, ledger, model.codec, model.graph, model.ids, model.policy, model.schema, realize.facts, realize.mapping]
status: specified
---
## Acceptance criteria
- AC1: If a critic's finding quotes words that are not in the text, then arch shall refuse the finding.
- AC2: If a critic's finding names a question the rubric does not ask of that kind of text, then arch shall refuse the finding.
- AC3: When a node under a critique policy has changed since its last critique, the check shall ask for a critique.
- AC4: When a critic's answer is recorded, each node it reviewed shall count as critiqued until its text changes.
- AC5: When a calibration answer is recorded, arch shall score each question's examples instead of storing findings.
- AC6: A request shall give the critic each node's text, with only its parent, its siblings and its needs as context.
- AC8: When a component has code, its request shall give its public declarations as its interface, and a finding may quote them.
- AC9: When a node was critiqued at its current text under an older rubric, its request shall ask only the questions added since.
- AC10: If a critic's finding names a question that was not asked of that node, then arch shall refuse the finding.
- AC7: Every rubric question shall state its principle and carry one example it flags and one it lets pass.

