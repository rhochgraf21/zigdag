---
answer: accepted
by: claude
findings:
  - {rule: criterion-is-constraint, subject: arch, key: arch-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch, key: arch-criterion-is-constraint-1}
  - {rule: criterion-is-constraint, subject: arch.change, key: arch-change-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.change.apply, key: arch-change-apply-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.change.ops, key: arch-change-ops-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.guide, key: arch-guide-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.integrate.catalog, key: arch-integrate-catalog-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.integrate.mcp, key: arch-integrate-mcp-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.realize, key: arch-realize-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.realize, key: arch-realize-criterion-is-constraint-1}
  - {rule: criterion-is-constraint, subject: arch.realize.facts, key: arch-realize-facts-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.review.page, key: arch-review-page-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.view.render, key: arch-view-render-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.view.report, key: arch-view-report-criterion-is-constraint}
  - {rule: criterion-is-constraint, subject: arch.view.site, key: arch-view-site-criterion-is-constraint}
---
Real: each limits how parts are built, so it belongs to a constraint. Constraints cannot carry criteria or linked tests yet (raised as an idea on arch.model.schema), so each stays where its test links it until they can.
