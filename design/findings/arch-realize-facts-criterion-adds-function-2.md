---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.realize.facts
digest: d4e49954e7d1
evidence: An interface name shall need a description when a word of its name is missing from the names of its types
hint: "Move the rule to a check (for example in arch.check) and keep in facts only the data it needs: names, types, descriptions and inheritance."
---
This is a rule about when names need descriptions, which makes it a check, not a representation of facts. It adds a judging function to the schema that adapters are meant to depend on alone.
