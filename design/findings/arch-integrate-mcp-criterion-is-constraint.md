---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.integrate.mcp
digest: bb0254875a01
evidence: The server shall make no network connections.
hint: Remove AC2 and make sure the no-network constraint is scoped to cover this component.
---
A ban on network use limits how the part may be built rather than what it does. Written as a criterion of one part, it hides from the other parts it should bind, and the design already names a no-network constraint elsewhere.
