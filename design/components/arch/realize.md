---
kind: component
realizes: Relate the design to the artifacts that realize it, in both directions
solution: Language-neutral facts extracted from source snapshots by pluggable adapters, a mapping from artifacts to components, and scaffolding emitted from the design
hides: Knowledge of particular languages, report formats and version control
serves: [catch-departures, low-adoption-cost]
uses: [model]
exports: [facts, mapping]
status: specified
---
## Acceptance criteria
- AC1: Extraction shall be a pure function of (snapshot, config); the same snapshot shall yield identical facts.
- AC2: No component outside realize shall depend on a language adapter; adapters are supplied by the caller and selected by file pattern, with a language-specific adapter taking precedence over the structural one.
- AC3: Facts for an unchanged file shall be reusable, keyed by the file's content hash.

## Rationale
Keeping languages behind a fact schema is what makes the core general. A second adapter (TypeScript)
is the test of that claim. Adapters come in fidelity tiers (D11).
