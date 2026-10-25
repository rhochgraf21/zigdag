---
kind: question
station: requirements
source: critic
by: criterion-undecidable
subject: arch.check.conformance
digest: "13b298d42be4"
evidence: When a description only repeats its name and type
hint: "State the mechanical rule, for example: every word of the description, after stop words, appears in the name or in the names of its types."
---
The criterion does not say what counts as 'only repeats', so whether a description such as 'The user to notify' for `user: User` passes depends on the reader. A test cannot decide it as written.
