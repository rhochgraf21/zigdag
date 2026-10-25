---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.model.schema
digest: "7bee977f488e"
evidence: Acceptance criteria shall be parsed from `- ACn:` lines in the component body
hint: "Move the parsing to arch.model.codec, and keep here only what the schema defines: a criterion field whose ids have the form `<component>#ACn`."
---
Parsing body text is a function the requirement does not name. Defining kinds, fields and validity does not include reading Markdown, and the sibling arch.model.codec already owns converting design files into nodes.
