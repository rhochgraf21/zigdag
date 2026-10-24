# The design of arch, written as arch

This directory is the axiomatic design of `arch`, written in the format `arch` will read. It is
hand-maintained until `arch` exists. After that, the outline, matrices and plan below are generated
(`arch outline`, `arch diagram --matrix`, `arch plan`), and this page shrinks to the prose.

```
design/
  needs/          9 customer needs. Solution-neutral: what must be true for people, not how
  constraints/    9 constraints, inherited down the tree, mostly machine-checkable
  components/     43 components (34 leaves). The FR/DP hierarchy; directories = decomposition
  decisions/      11 decisions (Dxx) and 3 resolved contradictions (Xxx)
```

## How to read a component

```yaml
realizes: <functional requirement: what it must do>     # the FR
solution: <design parameter: how, at this level>         # the DP
hides:    <the decision it encapsulates (Parnas secret)>
uses:     [<siblings or exported parts it may depend on>] # = design-matrix row = allowed imports
exports:  [<children visible outside it>]                 # default: none
serves:   [<needs>]                                       # top level; children inherit
status:   draft | specified | contracted | verified       # strictness of checks scales with this
```

The body holds acceptance criteria (`- ACn:` lines, EARS-style "When …, … shall …"), with optional
Rationale and Alternatives. Constraints name their own scope (`applies_to`) and are inherited down the
tree. Ids come from paths (`components/arch/check/baseline.md` is
`arch.check.baseline`). References are written short and resolve by lexical scope. Interfaces and
contracts are **not** here: they live in code and link back by id (D03).

## Customer needs

| Need | Statement (abridged) | How we'd know |
|---|---|---|
| understand-system | Understand the whole and any part well enough to change it confidently | Newcomer's time to first correct change |
| right-context | Agents have the knowledge they need about intent and boundaries, no less, no more | Context per task; structure-violating edits |
| catch-departures | A departure from intended structure is noticed before it joins shared work | Violations reaching mainline ≈ 0 |
| proportional-review | Review effort is proportional to risk, not size | Review minutes vs. risk |
| trace-purpose | Every part traces to an end-user purpose; unneeded parts can be found | % code traced; parts removed |
| sound-reasoning | Real problems, best-available solutions, even when agents do the work | Wrong-problem rework |
| low-adoption-cost | Adoptable incrementally on existing code; upkeep < savings | Time to first value |
| compose-at-scale | Big systems from parts each understandable and verifiable alone | Change cost stays flat with size |
| durable-knowledge | The reasons behind the shape outlive the people and agents who made them | Rationale findable for any choice |

## Level 0

**FR0:** Maintain an explicit, checked model of a software system's intent and structure that humans
and agents use to understand and change it.
**DP0:** A local, deterministic design toolchain (library, CLI, MCP, agent skills) over plain-text
design files in the repository.

## Level 1: decomposition and design matrix

| Component | FR (realizes) | DP (solution) | Hides |
|---|---|---|---|
| model | Represent the design persistently and recursively, queryably | Immutable typed model + lossless codec + graph/matrix queries | Internal representation |
| realize | Relate design and realizing artifacts, both directions | Language-neutral facts from pluggable adapters + mapping + scaffolds | Languages, report formats, VCS |
| check | Decide well-formedness and conformance | Rule engine: statement, structure, conformance rules + baseline ratchet | Rule evaluation, finding identity |
| change | Change the design via validated, reviewable operations | Typed atomic ops → file edits as data; semantic diff | Edit semantics |
| guide | Lead structured reasoning and the next most valuable work | Deterministic advisors + tool-agnostic method documents | Heuristics, method content |
| view | Present the design at the detail each task needs | Pure renderers: context cards, outlines, diagrams, review, site | Selection, layout |
| integrate | Be present in existing human and agent workflows | I/O-owning workspace + one operation catalog + thin surfaces | Transports, FS, environment |

```
            model realize check change guide view integrate
model         X     .      .     .      .     .      .
realize       X     X      .     .      .     .      .
check         X     X      X     .      .     .      .
change        X     X      X     X      .     .      .
guide         X     X      X     X      X     .      .
view          X     X      X     X      .     X      .
integrate     X     X      X     X      X     X      X
```

**Decoupled** (lower-triangular), so there is a valid realization order and no FR depends on a later
DP. `guide` and `view` are independent of each other and can be built in parallel. Every child
matrix is decoupled or uncoupled. Two couplings were found and removed while making this design:
inference first lived in `realize` (D09), and skills first lived in `guide` (D10).

## Full outline (realization order within each level)

```
arch
├─ model ............ represent the design
│  ├─ schema          node kinds, fields, validity
│  ├─ codec           files ↔ nodes, losslessly
│  ├─ graph           ancestry, visibility, inherited constraints, traceability
│  └─ matrix          design matrix, coupling class, realization order
├─ realize .......... relate design ↔ realization
│  ├─ facts           language-neutral facts: the adapter contract (exported)
│  ├─ evidence        JUnit / coverage / benchmark / mutation reports → evidence
│  ├─ history         git log → churn, co-change
│  ├─ mapping         source unit → component (exported)
│  ├─ python          Python adapter (semantic tier)
│  │  ├─ extract      AST → imports, API, ports, contracts, effects, links
│  │  └─ scaffold     create a component's starting code once
│  └─ treesitter      any language with a grammar (structural tier, draft)
├─ check ............ well-formedness and conformance
│  ├─ engine          rules → findings with stable identity (exported)
│  ├─ baseline        ratchet: only new findings block
│  ├─ conformance     imports, effects, evidence, budgets vs. design
│  ├─ statements      solution-in-need, compound, vague, non-EARS
│  └─ structure       dangling, orphans, span, coupling, secrets, loosened constraints
├─ change ........... validated design edits
│  ├─ diff            semantic diff, classified intent / structure / policy / prose
│  ├─ ops             add, set, remove, move, link, unlink (JSON)
│  └─ apply           atomic batch → design + minimal edits
├─ guide ............ structured reasoning
│  ├─ infer           brownfield: draft decomposition that starts green
│  ├─ method          elicitation, EARS, zigzag + secrets, TRIZ/ASIT, review
│  ├─ next            rank the most valuable next action
│  └─ plan            impact + parallel layers for agents
├─ view ............. right detail for each task
│  ├─ context         the context card for a component or file:line
│  ├─ diagram         containment / dependency / DSM, stable layout, change marks
│  ├─ outline         this view
│  ├─ review          layered, risk-ranked PR summary
│  └─ site            static browsable site (draft, last)
└─ integrate ........ be where work happens (only place with I/O)
   ├─ workspace       files, git, content-hash cache, atomic writes
   ├─ catalog         every operation defined once
   ├─ agent           skills + hooks per agent product, AGENTS.md fallback
   ├─ ci              check + review summary in CI (draft)
   ├─ cli             primary surface; --json; exit codes
   └─ mcp             same catalog over stdio (draft)
```

## Realization plan (what `arch plan` will print)

Leaf components grouped so each layer depends only on earlier layers. Items in a layer can go to
separate agents in parallel.

```
L0  model.schema · realize.facts · guide.method
L1  model.codec · model.graph · change.ops · realize.evidence · realize.history
    realize.python.extract · realize.python.scaffold · realize.treesitter
L2  model.matrix · realize.mapping · check.engine · change.diff · view.outline · guide.infer
L3  check.baseline · check.conformance · check.statements · check.structure · guide.next
    guide.plan · view.context · view.diagram · integrate.workspace
L4  change.apply · view.review · view.site
L5  integrate.catalog
L6  integrate.cli · integrate.agent · integrate.ci · integrate.mcp
```

The design rules that must settle first, since the most depends on them: `model.schema` and
`realize.facts`.

## Constraints

| Constraint | Applies to | Rule |
|---|---|---|
| no-network | arch | effects forbid network |
| deterministic | arch | effects forbid time, random; no run-dependent output |
| plain-text | arch | everything committed is diffable, stably ordered text |
| agent-neutral | arch | no LLM calls; product-specific code only in `integrate.agent` |
| typed-ports | arch | no bare built-ins in port signatures, except the CLI/MCP parse boundary |
| dependency-allowlist | arch | runtime: ruamel.yaml, deal; optional extras: mcp, tree-sitter |
| edit-loop-speed | arch | context p95 ≤ 300 ms; scoped check p95 ≤ 1 s; cold full ≤ 30 s |
| pure-core | model, realize, check, change, view, guide | no effects at all |
| shell-io | integrate | fs/subprocess(git)/stdio, *directly* only in workspace, cli, mcp |

## Decisions and contradictions

| | Decision |
|---|---|
| D01 | No LLM calls in arch: deterministic rules in `check`, judgement in methods run by the user's agent |
| D02 | One Component node = FR + DP + secret; four node kinds total |
| D03 | Interfaces and contracts live in code; the design links by id; scaffold once |
| D04 | Declared `uses` *is* the design matrix *and* the allowed-import set |
| D05 | Functional core, imperative shell; effects tracked as direct vs. transitive |
| D06 | arch reads evidence reports; CI runs the tools |
| D07 | Git is the transaction log: no proposal store |
| D08 | Ids are paths; the directory tree is the decomposition |
| D09 | Inference belongs to `guide` (removed a coupling) |
| D10 | Method content (`guide`) separate from skill packaging (`integrate`) (removed a coupling) |
| D11 | Adapter fidelity tiers: structural (tree-sitter) and semantic (per language); "not analyzed" never passes |
| X01 | Rigor vs. ceremony → maturity levels (time); the agent authors (closed world) |
| X02 | Context completeness vs. size → neighbours by external spec only (information hiding) |
| X03 | Strictness vs. adoption → baseline ratchet (time); maturity-scaled severity (condition) |

## Traceability: needs → components

| Need | Served by |
|---|---|
| understand-system | view |
| right-context | view, integrate |
| catch-departures | realize, check, integrate |
| proportional-review | change, view |
| trace-purpose | model, check |
| sound-reasoning | check, guide |
| low-adoption-cost | realize, guide, integrate |
| compose-at-scale | model, check, guide |
| durable-knowledge | model, change |

`understand-system` rests on `view` alone. That is the thinnest need, and the one to watch.

## Suggested v1 cut

Everything through L5, plus `integrate.cli` and `integrate.agent` (Claude Code adapter + AGENTS.md
fallback), with these exceptions: `realize.evidence` reads JUnit only; `view.diagram` renders Mermaid
only; `guide.infer` arrives in v1.1; `view.site`, `integrate.mcp` and `integrate.ci` come after.
Success criterion: arch's own design passes `arch check` with an empty baseline (arch AC5), and arch's
own code is developed through `arch context` / `arch check`.

## Open questions

1. **Acceptance criteria as lines or nodes?** Lines in the component body (current) are compact;
   separate nodes would allow richer links (one criterion to many tests) at the cost of many more files.
2. **Non-code coupling.** `uses` covers code dependencies only. Shared databases, timing and ordering
   couple components too. Is that a field, or always a contradiction record?
3. **Budget composition.** Child budgets ≤ parent is checked; latency along call chains is not yet
   specified.
4. **Cross-repository composition.** How a parent design references a versioned sub-design from another
   repo (the multi-repo / Terraform-module story). Leaning toward `uses: [pkg:billing@2]`, against
   that package's published external spec.
5. **EARS strictness.** Warning or error at `contracted`?
6. **CLI library.** Standard-library argparse for now (no dependency; hidden behind `integrate.cli`).
7. **Second adapter.** TypeScript (semantic) proves the fact schema is neutral; Mojo via tree-sitter
   (structural) is the exciting one. Both wait until the Python path is proven.
8. **Name.** `arch` collides with `/usr/bin/arch` and with the `arch` package on PyPI (see DESIGN.md §13).
