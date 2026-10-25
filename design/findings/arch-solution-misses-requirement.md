---
kind: question
station: solution
source: critic
by: solution-misses-requirement
subject: arch
digest: f01c19fd1f95
evidence: reads plain-text design files kept in the repository
hint: "State the whole design parameter, for example: a local, deterministic toolchain that keeps the design as plain-text files in the repository, changes them through validated operations, checks them against facts read from the code, and renders views for people and agents."
---
The solution covers how the model is stored and read, but not how it is checked against the code, changed, or presented to people and agents, all of which the requirement implies. Children such as change, realize, review and view then follow from the requirement rather than from the chosen solution.
