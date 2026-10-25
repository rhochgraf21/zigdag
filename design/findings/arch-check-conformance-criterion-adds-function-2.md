---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.check.conformance
digest: "13b298d42be4"
evidence: conformance shall ask whether it is shallow
hint: Move AC16 to the same code-quality sibling as the description rules, or reword it as a departure (for example, a part whose design hides a decision but whose code exposes that decision).
---
Asking whether a module is shallow judges the depth of the code's modules, not whether the code departs from the design. That is a separate function with no design parameter of its own.
