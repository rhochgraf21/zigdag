---
kind: component
realizes: Distinguish existing findings from new ones so only new ones block
solution: A committed, sorted, one-finding-per-line file of finding identities, updated only by an explicit baseline operation, from which fixed findings drop out automatically
hides: Baseline format and matching
uses: [engine]
status: specified
---
## Acceptance criteria
- AC1: A finding whose identity is in the baseline shall not block.
- AC2: When a baselined finding no longer occurs, the next baseline update shall remove it, so it cannot silently return.
- AC3: The file shall be sorted with one finding per line, so concurrent changes rarely conflict.
