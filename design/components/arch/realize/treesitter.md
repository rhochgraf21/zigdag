---
kind: component
realizes: Relate code in languages without a dedicated adapter to the design, at structural fidelity
solution: A generic adapter that runs tree-sitter grammars with one query file per language, yielding units, imports, public symbols and design links
hides: Grammar loading and query evaluation
uses: [facts]
status: draft
---
## Acceptance criteria
- AC1: Adding a language shall need only a grammar and a query file, with no adapter code.
- AC2: Units shall declare the capabilities structure, api and links, and never effects, ports or contracts.
- AC3: When no grammar is installed for a file's language, its unit shall be reported as not analyzed rather than omitted.

## Rationale
Cheap breadth: boundary checks, matrices, mapping, hotspots and links across many languages at once.
Syntax only, with no name or type resolution, so it makes no semantic claims. First candidates are
Mojo (where no semantic adapter is realistic yet) and TypeScript (until a semantic adapter exists).
Shipped as an optional extra so the base install stays small.
