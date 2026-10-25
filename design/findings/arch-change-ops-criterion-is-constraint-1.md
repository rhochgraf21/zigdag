---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.change.ops
digest: c378fcc6c5eb
evidence: so operations never read or write files on disk or handle transactions
hint: Record the no-I/O rule as a constraint on the pure core (or as a decision on arch.change), and keep criteria about what applying an operation produces.
---
AC5 limits how operations may be built (no file I/O, no transactions, go through a Draft protocol) rather than stating what an operation does. As a criterion it stays hidden from arch.change.apply and the workspace, which it also binds.
