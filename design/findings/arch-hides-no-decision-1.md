---
kind: question
station: solution
source: critic
by: hides-no-decision
subject: arch
digest: "5d90c9433e37"
evidence: How the design and the code are kept in step
hint: Name one decision that users never see and that is likely to change, such as 'How facts are extracted from each source language' or 'How design files are parsed and stored internally'.
---
Keeping design and code in step is arch's main visible service (AC2), and the decisions expose how it works to users, whose code links to the design by id (`@realizes("x#AC2")`). Users therefore depend on it, and it spans linking, extraction and checking rather than naming one volatile decision that arch keeps to itself.
