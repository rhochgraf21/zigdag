---
kind: question
station: requirements
source: critic
by: criterion-undecidable
subject: arch.check.quality
digest: b6ef97f96baf
evidence: When an interface name needs a description and has none
hint: "State the rule, for example: 'When an exported name has no description and its type is a built-in or its name differs from its type's name, the check shall report a defect at the interface station.'"
---
Whether a name 'needs' a description is left to judgement, so no test can decide when this criterion should fire. The criterion yields no evidence until the condition is stated.
