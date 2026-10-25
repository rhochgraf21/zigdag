---
answer: fixed
by: robert
findings:
  - {rule: requirement-not-from-parent, subject: arch.realize.python.names, key: arch-realize-python-names-requirement-not-from-parent}
---
The parent's solution now names the name resolver the extractor uses, beside the extractor and the scaffold emitter. It stays a sibling of extract rather than a child, because review explanations use it without extracting facts.
