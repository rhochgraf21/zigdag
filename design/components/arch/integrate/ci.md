---
kind: component
realizes: Run arch's checks and review summary on every proposed change
solution: A CI recipe that checks each change against its merge base and writes the review summary for the CI system to post
hides: CI-system specifics
uses: [catalog]
status: draft
---
## Acceptance criteria
- AC1: arch shall write the review summary to a file, and the CI system shall post it.
- AC2: CI shall fail only on blocking findings that are new relative to the baseline.
