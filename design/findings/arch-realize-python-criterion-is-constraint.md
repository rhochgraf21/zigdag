---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.realize.python
digest: "26bbe61178ee"
evidence: "AC1: The adapter shall never import or execute user code."
hint: Record it as a constraint on the realize parts (or on the whole system), for example 'Realization never imports or executes user code', and drop it from this component's criteria.
---
This limits how the adapter may be built (static analysis only), not what it does. Written as one adapter's criterion, it hides from the sibling adapters and extractors that the same safety limit should bind.
