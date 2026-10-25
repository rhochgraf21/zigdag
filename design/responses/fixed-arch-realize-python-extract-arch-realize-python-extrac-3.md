---
answer: fixed
by: robert
findings:
  - {rule: requirement-two-functions, subject: arch.realize.python.extract, key: arch-realize-python-extract-requirement-two-functions}
---
Name resolution is its own part now, arch.realize.python.names, which owns the module and function scopes; the extractor uses it to resolve calls and effects. extract's requirement is back to extracting facts, and AC8 and AC10 moved with their tests.
