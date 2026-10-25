---
answer: fixed
by: claude
findings:
  - {rule: hides-no-decision, subject: arch, key: arch-hides-no-decision-1}
---
Removed: a root has no siblings to hide a decision from, which is why S006 asks a secret only of non-root parts.
