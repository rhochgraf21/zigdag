---
kind: defect
station: requirements
source: critic
by: critic-3
subject: arch.realize.python.extract
digest: ef91cd0b59f8
evidence: Calls that cannot be resolved statically shall yield effect
---
AC3 said unresolved calls yield unknown, while the part's first decision rejects exactly that and charges effects where the object was obtained.
