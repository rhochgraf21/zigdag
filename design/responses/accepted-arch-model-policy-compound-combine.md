---
answer: accepted
by: claude
findings:
  - {rule: S104, subject: arch.model.policy, key: compound:combine}
  - {rule: S104, subject: arch.review, key: compound:get}
  - {rule: S104, subject: arch.review.session, key: compound:tell}
---
Real: each joins two functions. They are split into components later in this change series, using arch split.
