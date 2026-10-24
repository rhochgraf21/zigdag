---
kind: component
realizes: Run arch's checks and review summary on every proposed change
solution: A CI recipe (GitHub Actions first) that runs check against the merge base and writes the review summary to a file for the CI system to post
hides: CI-system specifics
uses: [catalog]
status: draft
---
## Acceptance criteria
- AC1: arch shall write the summary to a file; posting it is the CI system's job, so arch never uses the network.
- AC2: CI shall fail only on blocking findings that are new relative to the baseline.
