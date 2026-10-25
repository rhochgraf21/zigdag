---
kind: component
realizes: Have design text judged by an independent critic against a rubric
solution: A rubric as data, requests that give a critic only the text and its context, and answers kept only where the critic quotes the text
hides: The rubric's questions and how answers are judged
uses: [engine, ledger, model.codec, model.graph, model.ids, model.policy, model.schema]
status: specified
---
## Acceptance criteria
- AC1: If a critic's finding quotes words that are not in the text, then arch shall refuse the finding.
- AC2: If a critic's finding names a question the rubric does not ask of that kind of text, then arch shall refuse the finding.
- AC3: When a node under a critique policy has changed since its last critique, the check shall ask for a critique.
- AC4: When a critic's answer is recorded, each node it reviewed shall count as critiqued until its text changes.
- AC5: When a calibration answer is recorded, arch shall score each question's examples instead of storing findings.
- AC6: A request shall give the critic each node's text, with only its parent, its siblings and its needs as context.
- AC7: Every rubric question shall state its principle and carry one example it flags and one it lets pass.

