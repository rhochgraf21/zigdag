---
answer: declined
by: claude
findings:
  - {rule: C016, subject: arch.review.session, key: shallow}
---
Most of its interface is the fields of Verdict and Anchor, which the page and the server must read. Behind it are the rules for staleness, blocking and progress. Merging it into arch.review would put those rules in a parent that has no code.
