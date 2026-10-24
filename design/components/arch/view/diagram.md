---
kind: component
realizes: Show structure visually, in forms that stay stable across revisions
solution: A diagram model rendered to Mermaid, Graphviz and SVG, with overlays for effects, coupling and change
hides: Diagram construction and target formats
uses: [render, outline, check.engine, model.graph, model.ids, model.matrix, model.schema, realize.facts, realize.history, realize.mapping, change.diff]
status: specified
---
## Acceptance criteria
- AC1: The same design shall produce byte-identical diagram output.
- AC2: A diff diagram shall show only changed nodes and their direct neighbours, marked added, removed or changed.
- AC3: Matrix rows and columns shall follow realization order, so a decoupled design appears lower-triangular.
- AC4: The matrix shall be able to overlay observed imports and co-change on declared uses, distinguishing declared, undeclared and hidden coupling (co-change without dependency).
- AC5: The diagram of a component's parts shall omit uses implied by other uses (transitive reduction) unless all edges are asked for, keeping exactly the same reachability.
- AC6: When the effects overlay is on, each part shall be marked pure, effectful within its constraints, violating them, or unknown (no code or not analyzed).
- AC7: Mermaid and Graphviz output shall be rendered from the same diagram model, and the Markdown format shall be a fenced Mermaid block.
- AC8: When drawing a before and after pair, both sides shall be laid out over the union of their parts, with a part missing on one side drawn there as a ghost.
- AC9: When a before and after pair has more layers than fit across a page, the layers shall run top to bottom.

## Decisions
### Diagrams are generated views, never sources
- Chose: every diagram is rendered on demand from the design and facts; none is committed.
- Over: hand-drawn or committed diagrams.
- Because: a drawn diagram drifts from the code within weeks and then nobody trusts it; a generated one cannot drift.
- Consequences: publish diagrams from CI or paste them into pull requests; the design files stay the only source.

### Transitively reduced by default
- Chose: omit a use when another path of uses already implies it; `--all-edges` and the matrix show everything.
- Over: drawing every declared use.
- Because: arch's own top level has 21 uses among seven parts; drawn in full it is a hairball, reduced it is a readable chain.

### Mermaid first, Graphviz second, a site later
- Chose: Mermaid (renders in GitHub, GitLab and editors with nothing installed) and Graphviz for exports, both from one diagram model.
- Over: a browsable site first.
- Because: diagrams are useful now wherever people already look; the site is a larger front-end commitment, and can reuse the same model when it comes.
