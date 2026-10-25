---
answer: fixed
by: robert
findings:
  - {rule: interface-leaks-storage, subject: arch.model.codec, key: arch-model-codec-interface-leaks-storage}
---
scalar, render and YamlScalar are private. The ledger writes through codec.document from plain values (AC4), and every existing ledger file renders back byte for byte. The property test for it found three older quoting bugs, now fixed: control characters, NEL inside quotes, and brackets or commas inside one-line lists.
