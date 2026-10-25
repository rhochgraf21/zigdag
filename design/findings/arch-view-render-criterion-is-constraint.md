---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.view.render
digest: b6640bda950c
evidence: Every view and report shall render through the Rendering protocol, returning Markdown and JSON values rather than bare strings and dictionaries.
hint: Record it as a constraint applied to arch.view and its children, and give this part a criterion about its own types, for example how a Markdown value and a JSON value of the same content compare.
---
This limits how every other view and report may be built (which types they use), not what this part does. Written as this part's criterion, it hides from the sibling parts it actually binds.
