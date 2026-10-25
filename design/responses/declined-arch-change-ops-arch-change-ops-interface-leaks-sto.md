---
answer: declined
by: robert
findings:
  - {rule: interface-leaks-storage, subject: arch.change.ops, key: arch-change-ops-interface-leaks-storage}
---
NodeFile is the codec's edit model, not the storage format: operations set fields and sections by name, and YAML, quoting and layout stay inside the codec. Editing through it is what restores a file byte for byte (AC4); turning model diffs into file edits in apply would move that layout knowledge out of the codec. AC5 now says what it meant: operations never read or write files on disk.
