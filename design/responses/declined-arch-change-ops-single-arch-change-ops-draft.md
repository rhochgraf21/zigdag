---
answer: declined
by: claude
findings:
  - {rule: C019, subject: arch.change.ops, key: single:arch.change.ops.Draft}
---
The protocol inverts a dependency: apply imports the operations, so the operations cannot import apply's draft. With the protocol they edit a draft and never touch files, and no cycle forms.
