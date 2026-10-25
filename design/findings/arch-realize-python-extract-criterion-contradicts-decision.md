---
kind: question
station: requirements
source: critic
by: criterion-contradicts-decision
subject: arch.realize.python.extract
digest: ef91cd0b59f8
evidence: When a call cannot be resolved, its effects shall be charged where the object it is called on was obtained
hint: "Add the exception to the criteria, e.g. AC3: \"...where the object it is called on was obtained, except that in units that use pathlib, distinctive pathlib methods count as file effects at the call whatever the receiver\". Otherwise drop the pathlib decision."
---
AC3 charges every unresolved call where its receiver was obtained. The decision "Distinctive pathlib methods count on any receiver" charges `.read_text()`, `.rglob()` or `.mkdir()` on an unknown receiver as a file effect at the call site. A function that is handed a path and calls `.read_text()` on it gets one answer from AC3 and the opposite from the decision, so its behaviour is undecided.
