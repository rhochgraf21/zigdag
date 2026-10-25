---
kind: question
station: interface
source: critic
by: interface-flag-picks-behaviour
subject: arch.integrate.catalog
digest: c400e447dc93
evidence: "edit(ws: Workspace, operations: Sequence[DesignOperation], mode: EditMode=EditMode.WRITE) -> Result"
hint: Make the preview its own read operation (for example preview_edit) next to a write-only edit, and do the same for init, so each operation's declared access is true.
---
The mode chooses whether the operation writes the design or only previews the edit, so one operation holds two behaviours (init has the same mode). It also undermines AC1: each Operation declares a single Access, but whether edit writes depends on the argument.
