---
kind: constraint
applies_to: [arch.model, arch.realize, arch.check, arch.change, arch.view, arch.guide]
rule:
  effects:
    allow: []
---
Core components compute; they never touch the filesystem, processes, environment, terminal, clock or
network. They take snapshots as data and return results (including file edits) as data. This makes the
whole core property-testable and cacheable.
