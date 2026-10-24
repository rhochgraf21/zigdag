---
kind: component
realizes: Relate the design to the artifacts that realize it, in both directions
solution: Language-neutral facts extracted from source snapshots by pluggable adapters, a mapping from artifacts to components, and scaffolding emitted from the design
hides: Knowledge of particular languages, report formats and version control
serves: [catch-departures, low-adoption-cost]
uses: [model]
exports: [facts, history, mapping]
status: specified
---
## Acceptance criteria
- AC1: Extraction shall be a pure function of (snapshot, config); the same snapshot shall yield identical facts.
- AC2: No component outside realize shall depend on a language adapter. realize selects among its built-in adapters by file pattern; a caller may add adapters implementing the protocol in `realize.facts`, and added adapters take precedence, as does a language-specific adapter over the structural one.
- AC3: Facts for an unchanged file shall be reusable, keyed by the file's content hash.
- AC4: After extraction, effects shall be propagated across the project: a symbol has every effect of the project symbols it calls, computed to a fixed point, and each added effect records the call it came through.

## Rationale
Keeping languages behind a fact schema is what makes the core general. A second adapter (TypeScript)
is the test of that claim.

## Decisions
### Two adapter tiers behind one fact schema
- Chose: structural adapters (a tree-sitter grammar plus a query file: units, imports, public symbols, links) and semantic adapters per language (adding ports, contracts, effects); every unit records what was analyzed, and checks that need something missing report "not analyzed".
- Over: a hand-built semantic adapter for every language, or one generic adapter for all of them.
- Because: breadth stays cheap and honest; arch never claims a module is pure when it could not look.
- Consequences: effect constraints are enforced only where a semantic adapter exists, and reports say so. Python's semantic adapter uses stdlib `ast`, which is exact and needs no dependency.
