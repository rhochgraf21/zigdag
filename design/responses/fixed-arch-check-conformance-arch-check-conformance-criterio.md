---
answer: fixed
by: claude
findings:
  - {rule: criterion-adds-function, subject: arch.check.conformance, key: arch-check-conformance-criterion-adds-function-1}
  - {rule: criterion-adds-function, subject: arch.check.conformance, key: arch-check-conformance-criterion-adds-function-2}
---
Split with arch split into arch.check.quality, which judges interface quality. Conformance keeps departures from the design.
