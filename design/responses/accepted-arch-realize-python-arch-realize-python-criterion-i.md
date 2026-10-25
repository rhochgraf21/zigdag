---
answer: accepted
by: robert
findings:
  - {rule: criterion-is-constraint, subject: arch.realize.python, key: arch-realize-python-criterion-is-constraint}
---
Right: it is a safety limit for every realize part, not one adapter's behaviour. It stays here for now because a constraint cannot carry the criterion its test realizes (idea findings/arch-model-schema-constraints-cannot-carry-acceptance-criter.md) and there is no operation to add a constraint (findings/arch-change-ops-there-is-no-operation-to-add-a-constraint-or.md). Move it when either lands.
