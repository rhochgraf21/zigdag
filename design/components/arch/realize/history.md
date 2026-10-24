---
kind: component
realizes: Extract change history, meaning churn per unit and units that change together
solution: A parser for `git log --numstat` output supplied by the workspace, with co-change counted over a window of recent commits
hides: Version-control log format
uses: [facts]
status: specified
---
## Acceptance criteria
- AC1: Co-change shall count only commits touching at most N files (default 30), so mass edits do not create false coupling.
- AC2: The window shall be measured in commits, not time, so the same log yields the same facts.
