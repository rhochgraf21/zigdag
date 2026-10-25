---
answer: fixed
by: claude
findings:
  - {rule: constraint-is-function, subject: agent-neutral, key: agent-neutral-constraint-is-function}
  - {rule: criterion-adds-function, subject: arch.check.engine, key: arch-check-engine-criterion-adds-function}
  - {rule: criterion-undecidable, subject: arch, key: arch-criterion-undecidable}
  - {rule: criterion-undecidable, subject: arch.integrate.agent, key: arch-integrate-agent-criterion-undecidable}
  - {rule: criterion-undecidable, subject: arch.integrate.catalog, key: arch-integrate-catalog-criterion-undecidable}
  - {rule: criterion-undecidable, subject: arch.model.schema, key: arch-model-schema-criterion-undecidable}
  - {rule: criterion-undecidable, subject: arch.realize.facts, key: arch-realize-facts-criterion-undecidable}
  - {rule: criterion-undecidable, subject: arch.realize.python.extract, key: arch-realize-python-extract-criterion-undecidable}
  - {rule: criterion-undecidable, subject: arch.review.page, key: arch-review-page-criterion-undecidable}
  - {rule: hides-no-decision, subject: arch.change.apply, key: arch-change-apply-hides-no-decision}
  - {rule: hides-no-decision, subject: arch.model.matrix, key: arch-model-matrix-hides-no-decision}
  - {rule: hides-no-decision, subject: arch.realize.facts, key: arch-realize-facts-hides-no-decision}
  - {rule: hides-no-decision, subject: arch.review.summary, key: arch-review-summary-hides-no-decision}
  - {rule: hides-no-decision, subject: arch.view.render, key: arch-view-render-hides-no-decision}
  - {rule: need-names-solution, subject: low-adoption-cost, key: low-adoption-cost-need-names-solution}
  - {rule: need-signal-unobservable, subject: compose-at-scale, key: compose-at-scale-need-signal-unobservable}
  - {rule: need-signal-unobservable, subject: low-adoption-cost, key: low-adoption-cost-need-signal-unobservable}
  - {rule: need-signal-unobservable, subject: proportional-review, key: proportional-review-need-signal-unobservable}
  - {rule: requirement-not-from-parent, subject: arch.realize.evidence, key: arch-realize-evidence-requirement-not-from-parent}
  - {rule: requirement-not-from-parent, subject: arch.realize.history, key: arch-realize-history-requirement-not-from-parent}
  - {rule: requirement-not-from-parent, subject: arch.review.assess, key: arch-review-assess-requirement-not-from-parent}
  - {rule: requirement-not-from-parent, subject: arch.review.summary, key: arch-review-summary-requirement-not-from-parent}
  - {rule: requirement-states-how, subject: arch.integrate.server, key: arch-integrate-server-requirement-states-how}
  - {rule: requirement-two-functions, subject: arch.guide, key: arch-guide-requirement-two-functions}
  - {rule: requirement-two-functions, subject: arch.model.policy, key: arch-model-policy-requirement-two-functions}
  - {rule: requirement-two-functions, subject: arch.review, key: arch-review-requirement-two-functions}
  - {rule: solution-misses-requirement, subject: arch, key: arch-solution-misses-requirement}
  - {rule: solution-misses-requirement, subject: arch.guide.next, key: arch-guide-next-solution-misses-requirement}
  - {rule: solution-misses-requirement, subject: arch.review, key: arch-review-solution-misses-requirement}
  - {rule: solution-misses-requirement, subject: arch.review.page, key: arch-review-page-solution-misses-requirement}
  - {rule: solution-misses-requirement, subject: arch.view.diagram, key: arch-view-diagram-solution-misses-requirement}
---
Reworded as the finding asked: the statement now says one thing, says it decidably, or names what was missing.
