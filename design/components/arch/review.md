---
kind: component
realizes: Let a person review a change one decision at a time, and get their verdicts back to its author
solution: Review pages built from the design diff and the code diff, with verdicts kept against each page's content
hides: How a change is cut into review pages
serves: [proportional-review, catch-departures, sound-reasoning]
uses: [model, realize, check, change, view]
exports: [summary, assess, items, page, session]
status: specified
---
## Acceptance criteria
- AC1: When a change is reviewed, every changed need, requirement, criterion, decision, constraint, structural change, breaking or uncertain port change and changed file shall appear on exactly one review page.
- AC2: Review pages shall be ordered overview, needs and requirements, architecture, constraints, design decisions, interfaces, then code component by component in build order, so a component is reviewed after what it depends on.

## Decisions
### Verdicts stay local; outcomes go into the design
- Chose: verdicts, comments and notes in .arch/reviews/ (git-ignored), read by the agent through `arch review --feedback`; what the review decided becomes decision entries or requirement changes, and `--record` summarises it for the commit or PR
- Over: committing review sessions to the repository
- Because: working state churns and is worthless after merge, and committing it would put commits on the author's branch for every click; what lasts already has a home in the design
- Consequences: agents on another machine cannot read local verdicts; they will get them through the pull request when that is built

### Agents cannot record verdicts
- Chose: recording a verdict is a human-only catalog operation that MCP never offers; verdicts come only from the local page
- Over: letting any surface approve items
- Because: an author must not approve its own work (mistake-proofing), least of all an agent working unattended
