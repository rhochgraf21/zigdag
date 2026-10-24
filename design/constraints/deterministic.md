---
kind: constraint
applies_to: [arch]
rule:
  effects:
    forbid: [time, random]
---
The same inputs always produce the same outputs, byte for byte. No clock reads, no randomness, no
timestamps or run-dependent values in anything arch writes or prints. Windows over history are
measured in commits, not days; caches are keyed by content hash, not modification time.
