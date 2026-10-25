---
kind: question
station: requirements
source: critic
by: requirement-two-functions
subject: arch.review.assess
digest: "4586b89b0597"
evidence: and what evidence each touched criterion has
hint: Split into 'Judge how risky each changed file is' and a separate part that collects evidence for touched criteria, which the risk score then uses.
---
Two functions: scoring the risk of each changed file, and collecting the evidence for each touched criterion. They change for different reasons (risk weights versus evidence linking), and AC2 makes the score depend on evidence, which couples them inside one part.
