---
kind: question
station: requirements
source: critic
by: criterion-is-constraint
subject: arch.change
digest: "54197db5cd22"
evidence: Applying operations shall produce file edits as data, which the workspace writes.
hint: Drop AC3 and rely on the pure-core and shell-io constraints. If an observable check is wanted, state it as behaviour, for example that a --dry-run batch leaves every file unchanged.
---
This decides where I/O happens (edits as data, writes only in the workspace), which limits how the part is built rather than what it does. It repeats the pure-core and shell-io constraints that bind every part.
