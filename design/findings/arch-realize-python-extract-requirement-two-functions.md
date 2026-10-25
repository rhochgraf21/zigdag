---
kind: question
station: requirements
source: critic
by: requirement-two-functions
subject: arch.realize.python.extract
digest: a58903cd2c99
evidence: what names refer to
hint: Split name resolution into its own requirement, as a child or sibling component with a solution that says how definitions are resolved, or else narrow realizes to extracting the facts.
---
Besides extracting facts, the requirement asks for name resolution (definitions of names and the line each local's value came from). That is a second function, and the interface already offers it as a separate entry point, names(). The solution's visitor does not say how it resolves names.
