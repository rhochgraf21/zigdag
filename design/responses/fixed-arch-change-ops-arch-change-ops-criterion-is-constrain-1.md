---
answer: fixed
by: robert
findings:
  - {rule: criterion-is-constraint, subject: arch.change.ops, key: arch-change-ops-criterion-is-constraint-2}
---
AC5 is now a decision on arch.change.ops (operations edit through a Draft), backed by pure-core, which already forbids file effects in arch.change by machine. It had no test of its own, which fits: it is a choice about structure, not a behaviour.
