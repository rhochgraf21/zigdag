---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.model.schema
digest: "7bee977f488e"
evidence: A component's `## Decisions` section shall be parsed into entries
hint: Move the parsing to arch.model.codec, and state here only the decision entry type and its fields (title, text, labels, location).
---
Parsing a Markdown section into entries is a function the requirement does not name, and it overlaps arch.model.codec's job of converting files into nodes.
