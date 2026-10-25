---
answer: accepted
by: claude
findings:
  - {rule: criterion-adds-function, subject: arch.change, key: arch-change-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.check.conformance, key: arch-check-conformance-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.check.critique, key: arch-check-critique-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.check.ledger, key: arch-check-ledger-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.guide.infer, key: arch-guide-infer-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.integrate.agent, key: arch-integrate-agent-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.integrate.catalog, key: arch-integrate-catalog-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.model.schema, key: arch-model-schema-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.model.schema, key: arch-model-schema-criterion-adds-function-1}
  - {rule: criterion-adds-function, subject: arch.realize.facts, key: arch-realize-facts-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.realize.history, key: arch-realize-history-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.realize.mapping, key: arch-realize-mapping-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.realize.python.extract, key: arch-realize-python-extract-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.review.explain, key: arch-review-explain-criterion-adds-function}
  - {rule: criterion-adds-function, subject: arch.review.items, key: arch-review-items-criterion-adds-function}
---
Real: each adds a function to its part. Most belong to a sibling that already owns that function, and split cannot move criteria into an existing part yet (raised as an idea on arch.change.ops). Each is moved when it can be.
