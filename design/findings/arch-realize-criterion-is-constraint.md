---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.realize
digest: fbc20c97d98a
evidence: Extraction shall be a pure function of the snapshot and the configuration.
hint: Make purity of extraction a constraint scoped to arch.realize and its adapters, and keep AC5 as the criterion.
---
Purity limits how every adapter may be built (no file, network or clock access), so it is a constraint on all of realize's children. Written as a criterion on the parent, it is hidden from the adapters it binds, and AC5 already states the observable outcome.
