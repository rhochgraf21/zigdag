---
kind: question
station: requirements
source: critic
by: criterion-adds-function
subject: arch.realize.python.extract
digest: "0555cd135429"
evidence: Each use of a local variable shall resolve to the line that set the value it sees.
hint: Name it in realizes as an extracted output (for example 'local definitions and their uses'), or give reaching-definition analysis its own component.
---
Tracing which assignment reaches each use of a local variable is dataflow analysis. The requirement's list (units, imports, public API, ports, contracts, effect uses, design links) does not name it, so the visitor is not designed for it.
