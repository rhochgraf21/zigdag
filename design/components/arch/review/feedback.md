---
kind: component
realizes: Report what a review decided, for the author and for the commit
solution: Open change requests listed blocking first, each with the station where it was made, and a summary of the verdicts
hides: How requests are ranked and worded
uses: [session, items, model.ids, view.render, check.engine]
status: specified
---
## Acceptance criteria
- AC1: Feedback shall list open change requests, blocking ones first, each with its category, comment, anchor and item id.
- AC2: When a change request is open, the feedback shall say at which station it was made and how to record it as an escape.

