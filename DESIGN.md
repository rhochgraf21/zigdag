# arch: ideas, principles and the bet

This file keeps the thinking behind arch: why it exists, the ideas it borrows, what we decided against
and why, and where it might go. The formal design (needs, components, constraints, matrices and decisions) lives in
[`design/`](design/README.md). If the two disagree, `design/` wins and this file gets updated.

Status: proving out the method. Nothing here is settled because it sounds good; it is settled when it
pays off on arch itself.

---

## 1. The problem

Projects built with AI agents degrade past a certain size. Agents lose the big picture, guess at intent,
blur boundaries, and produce more code than anyone can review. Humans lose the ability to understand
and steer their own systems. The fix is not more prompting. It is making the system's **intent and
structure explicit, versioned and checked**, so agents and humans work from the same model and
departures from it are caught mechanically.

**The bet:** arch becomes essential if
1. the design is the **cheapest correct context** an agent can get, and
2. the review it produces is the **cheapest correct review** a human can do.

Every feature must serve one of these two. Anything that serves neither is ceremony and gets cut.

## 2. Where the ideas come from

| Source | What we take |
|---|---|
| Axiomatic design (Suh), extended and recursive | Customer needs → functional requirements → design parameters, zigzag decomposition, the **design matrix** (independence axiom), information axiom as "fewest assumptions". Recursion: every DP is a black box with an external spec and a sub-design of the same shape. |
| C4 model | Views of one model cut at chosen depths (system, container, component, code). Views, *not* the structure: recursion depth is arbitrary. |
| Parnas, information hiding | Decompose by **secrets** (decisions likely to change), not by processing steps. Every component records `hides:`. |
| Baldwin and Clark, *Design Rules* | Stable visible interfaces (design rules) let hidden modules evolve independently; modularity has option value. `realize.facts` and `model.schema` are arch's own design rules. |
| TRIZ | Record coupling as a contradiction (improving X worsens Y) and resolve it by separation in time, space, condition or system level. |
| ASIT | **Closed world**: solve with what is already in the system before adding anything. Default policy against sprawl. |
| Design by contract, deal | Pre/post/invariants and **effect declarations** (`deal.has`) on ports; contracts become property tests (`deal.cases`) and can be symbolically checked (CrossHair, `deal prove`). |
| Property-based testing (Hypothesis) | Agents write properties, not examples; one strategy per domain type, reused everywhere. |
| Assume/guarantee contracts | Parent correctness from children's guarantees. Effects, dependencies, budgets and types **compose mechanically**; functional correctness needs integration properties. |
| Fitness functions, ArchUnit, import-linter, Bazel visibility, Go `internal/` | Architecture as executable checks; boundaries enforced, not hoped for. |
| Functional core / imperative shell, hexagonal | Default effect layering, used by arch itself. |
| DDD | Bounded contexts at container level; the **ubiquitous language becomes domain types**. |
| EARS, INCOSE requirement rules | Deterministic grammar for requirements ("When ‹trigger›, the ‹system› shall ‹response›"). |
| ADRs | Decisions with context, alternatives and consequences, in the repo. |
| CodeScene, *Your Code as a Crime Scene* | Hotspots (churn × complexity) and **temporal coupling**: files that change together across a boundary reveal hidden coupling. |
| Mutation testing | Measures whether (agent-written) contracts and properties actually constrain anything. |
| DSM / Lattix | The design structure matrix as the whole-system view that scales past where diagrams turn into hairballs. |
| **Cautionary:** SysML / MBSE | Powerful, rigorous and resented. Separate tools, models apart from code, models nobody executes. Avoid all three. |
| **Nearest neighbours:** Kiro specs, Spec Kit, Tessl | Per-feature, flat, mostly disposable specs. arch's difference: a design that is **persistent, hierarchical and enforced**, still true and still checked two years later. |

## 3. Core model

Three node kinds, plain text in the repo, matching axiomatic design's domains:

- **Need**: solution-neutral customer need with stakeholder and signal ("how we'd know").
- **Component**: one node per FR/DP pair: `realizes` (FR), `solution` (DP), `hides` (secret),
  `uses`, `exports`, `serves`, `status`, plus acceptance criteria and **decisions** in the body.
  Recursive at every scale.
- **Constraint**: inherited policy (effects, imports, budgets, port typing). A constraint lists its own
  scope (`applies_to`); descendants may tighten it, never loosen it. Cross-cutting concerns (auth,
  audit, logging) are constraints, not FRs, which removes most false coupling.

**Decisions are not a separate kind.** In axiomatic design a decision *is* the choice of a DP, and the
information axiom is how you choose among candidates. So each decision lives on the component whose DP
embodies it, as a `### title` entry under `## Decisions` with `Chose:` / `Over:` / `Because:` lines
(plus `Consequences:`, `Previously:` for reversals, and `Backed by:` naming the constraints that make
it checkable). System-wide decisions live on the root. A coupling kept on purpose is an accepted answer
to the coupling finding, with the TRIZ resolution as one of the parent's decisions. The chronological decision log is a
view generated from git history, not a folder people maintain.

Key mechanics:

- **`uses` is the design matrix.** Declared sibling dependencies are the off-diagonal entries. Cycles mean
  coupled, acyclic means decoupled, none means uncoupled. The same declarations are the allowed imports,
  the realization order, the parallel work plan for agents, and the impact analysis.
- **Visibility.** Siblings and uncles are visible; deeper parts only through `exports`. Encapsulation is
  a property of the design.
- **Ids are paths.** The directory tree is the decomposition; references resolve by lexical scope.
- **Maturity** (draft → specified → contracted → verified). Checks tighten as a component matures.
  Formality is added where and when it pays.
- **Leaf rule.** Stop decomposing when one agent can implement a component and its tests in one focused
  session, its card fits on one screen, and it has one secret.
- **Span rule.** Roughly 7±2 children per node, so the top of any system, and every subtree, fits on a screen.

## 4. Who owns what (design vs. code)

The test for any field: **would two senior engineers argue about it in a design review?** If yes it
belongs in the design; if it can be derived or checked, arch derives it.

| Design owns (decisions) | Code owns (formalized) |
|---|---|
| Needs, requirements, acceptance criteria in prose | Interfaces: ports, or OpenAPI/proto/AsyncAPI at container level |
| Chosen solution, secret, rationale, alternatives | Contracts (deal), domain types and invariants |
| Constraints: effects, dependencies, budgets, visibility | Implementation, property tests, linked by id (`@realizes("x#AC2")`) |

- **No interfaces or contracts in YAML.** That is code without a type checker, bound to drift.
- **`sync`** = scaffold a component once (port stub, test stubs) and compile policy. It never touches code
  a human or agent has edited.
- **Drift** (code → design) is **detected and reported, never auto-applied**. Silently rewriting the
  design from code would remove the review gate that makes it worth having.
- **Brownfield inference** is the one sanctioned code → design path: a draft design whose `uses` equal
  observed imports, so adoption starts green and then tightens.

## 5. Agents first

Users manage the design *through their agent*; arch makes that safe and cheap.

- **Validated operations, not free-form edits:** add, set, move (rewrites references, including links in
  code), remove, link, unlink, atomic in batches, JSON-describable. Git is the transaction log.
- **Context cards** (`arch context <id | file:line>`): the chain up to needs, FR/DP/secret, acceptance
  criteria with evidence, port signatures and contracts, effective constraints, neighbours **only by
  external spec**, open findings, trimmed to a size budget.
- **`arch next`** ranks the most valuable next action; **`arch plan`** gives impact and parallel layers.
- **No LLM inside arch.** Mechanical judgements are deterministic rules; judgement calls are **methods**
  (elicit needs, solution-neutral rewriting, zigzag with secrets, TRIZ/ASIT contradiction resolution,
  design-diff review) run by the user's own agent, each ending in arch's deterministic self-check. The
  theory: structured thinking processes make agents behave like experts, and the deterministic gate
  stops the process from being skipped.
- **In the loop automatically:** hooks inject the card before an edit and run a scoped check after; CI
  gates on new findings. A tool you must remember to use stays optional.

## 6. Verification ladder

Escalate per component, by maturity and risk; never force formal methods everywhere.

1. **Domain types** at ports (no bare `str`/`int`/`dict`/`Any`): the cheapest contracts. Parse at the edge.
   Enums instead of bool flags and magic strings; `NewType` for zero-cost ids; frozen value objects
   with invariants. Inside a function, built-ins are fine.
2. **Contracts** (deal pre/post/ensure/inv) on ports, linked to acceptance criteria.
3. **Properties** (Hypothesis, `deal.cases`), with one registered strategy per domain type. The same
   property suite runs against every implementation of a port (real and fake), which keeps test
   doubles honest.
4. **Symbolic** (CrossHair, `deal prove`) for small pure functions where it is worth it.
5. **Mutation score** as a quality gate on contracts and properties.

**Effects as architecture:** `effects: none` on the core, network only in adapters, and so on, checked
statically (with direct vs. transitive effects distinguished) and backed by deal's runtime checks.
An effect is charged where code obtains access to an effectful API (an import such as `os`, `open`,
the clock) and reaches every caller arch can resolve; a call on an object that was merely handed in is
charged where that object came from. Importing a module is not using it; dynamic code is `unknown`.
**Performance:** budgets per component, gated by benchmark regression with tolerance; Scalene used for
*attribution*, with line-level CPU, memory and copy volume rolled up to components. arch reads reports;
CI runs the tools.

## 7. Review and visualization

**Review outside-in, with early exit and a risk gate.** Each layer is small, and the reviewer stops when
confident or when something is wrong:

1. **Intent**: one to three lines, which need or requirement changed and why
2. **Design diff**: requirement, constraint and decision changes in prose, with rationale
3. **Structure**: diagram of only the changed neighbourhood
4. **Contracts**: interface and contract diff with compatibility class (semver from design diffs)
5. **Evidence**: what machines proved (boundaries, effects, properties, mutation score, budget headroom)
6. **Code**: risk-ranked; verified internals with passing evidence collapsed

Delivered where reviewers already are (a generated PR comment), with a local page for depth.

**Making the whole digestible:**
- The **outline** (one-line FR→DP tree, realization order) is the best comprehension view, and it diffs cleanly.
- **Nested boxes with semantic zoom** for the spatial view; **DSM** for experts and scale.
- **Stable layout** (seeded, hierarchical) so diagram diffs don't reshuffle.
- **Overlays**: maturity, drift, evidence, budget headroom, hotspots.
- **Declared vs. observed coupling**: imports and co-change overlaid on declared uses expose hidden coupling.
- **`explain`** for any file or line: the component → requirement → need chain, plus the component's secret.

## 8. Not ceremony

1. **Value before effort**: on an existing repo, five minutes to a dependency map, DSM, hotspots, hidden
   coupling and a draft decomposition, with zero writing.
2. **Ratchet, don't gate**: baseline existing findings; only new ones block; fixed ones cannot return.
3. **One node is a valid project**; depth is earned by complexity.
4. **Same PR, same agent**: design changes ride with the code, authored by the agent, reviewed as a diff.
5. **The design pays rent daily**: cards, checks and plans make the agent's own work better, so it has a
   reason to keep the design current.
6. **Kill criteria, measured**: context per task, review minutes per PR, defect escapes, drift count, time
   to a newcomer's first correct change. If they don't improve on a real project, it's ceremony.

## 9. Languages and adapters

The core is language-neutral; everything language-specific sits behind `realize.facts`. Adapters come in
**fidelity tiers**, and every fact records what was and wasn't analyzed. A check that needs a capability
the adapter lacks reports "not analyzed"; it never passes silently (no false "pure").

| Tier | Capabilities | How |
|---|---|---|
| Structural | units, imports, public symbols, design links | **tree-sitter**: a grammar plus a query file per language, no adapter code |
| Semantic | + ports, contracts, effects (direct and transitive), call graph | a language-specific adapter using the language's own parser or compiler tooling |

- **Python** first, with a semantic adapter on stdlib `ast` (exact, zero dependencies, best fidelity for
  effects and deal contracts).
- **tree-sitter** is the cheap path to breadth: boundary checks, DSM, mapping, hotspots and links in many
  languages at once. It is syntax only (no type or name resolution), so it never claims effects.
  Shipped as an optional extra.
- **Mojo** is a great fit (traits as ports, explicit `raises`, performance budgets matter, Python
  interop), and would start at the structural tier via a tree-sitter grammar. Risks: grammar maturity,
  and Mojo syntax is still moving. Cross-language edges (Mojo importing Python modules) need the fact
  schema to allow imports across languages, which the language-neutral unit names already do.
- **TypeScript** is the natural first semantic adapter after Python: it proves the fact schema is
  really neutral.

## 10. Bigger systems (future, exploratory)

- **Infra and deployment are realizations** (AD process variables): DP → deploy unit → resources.
- **Check infra, mostly don't generate it.** Read Terraform plans and compose configs; compare to the
  design. Generate only narrow artifacts (least-privilege policies, a dev compose file).
- **Effects → permissions**: `effects: [db.read(orders)]` checked against IAM and network policy.
  Least privilege derived from architecture.
- **Interface language by level**: Protocols in code; OpenAPI, proto or AsyncAPI between containers; SQL
  schema for data. Referenced, never reinvented.
- **Semver from design diffs**, so sub-designs can be published and composed across repos by version.
- **Runtime architecture**: OpenTelemetry spans tagged with component ids; actual vs. designed call
  graph; requirement budgets become SLOs.

## 11. Decided against (and why)

| Idea | Why not |
|---|---|
| Interfaces and contracts in YAML | Code without tools, duplicated, drifts. Code owns them. |
| Separate FR and DP nodes | Doubles nodes for a 1:1 pairing. One Component node. |
| Decisions as a separate node kind (ADR folder) | Not from axiomatic design; duplicated component rationale (8 of our first 14 records); hand-kept `affects:` links nothing could check were complete. Decisions live on their component. |
| Six or more node kinds | Too much vocabulary for daily use. Three kinds. |
| Constraints listed on components *and* scoped on constraints | Two sources of truth; a constraint owns its scope (`applies_to`). |
| C4 levels = decomposition levels | Recursion is arbitrary depth; C4 levels are views. |
| `arch sync` rewriting design from code | Removes the review gate. Detect drift, propose changes. |
| Propose/apply proposal store | Git already does staging, review and undo. |
| arch runs tests and benchmarks | Slow, non-deterministic in the edit loop. arch reads reports. |
| LLM calls inside arch | Offline, deterministic, agent-neutral instead. Judgement in methods. |
| Generating Terraform wholesale | A worse Terraform. Check it; generate narrow artifacts. |
| Delegating boundary checks to import-linter | arch needs the import graph anyway for views and DSM. |
| A web app as the primary review surface | Reviewers live in PRs. PR summary first, site last. |

## 12. Proving the method

Hypotheses to test on arch itself, then on a brownfield project:

1. The matrix catches real design problems early. *(So far, two couplings caught in arch's own design: see the
   `Previously:` lines on `guide.infer` and `guide.method`.)*
2. Context cards cut agents' wrong guesses and wasted context, compared with reading the code.
3. Layered review cuts review time without missing defects.
4. Keeping the design current costs less than it saves when the agent does the writing.
5. A brownfield repo goes from nothing to a green, useful design in one sitting.

## 13. Open naming problem

`arch` collides twice. `/usr/bin/arch` is a system command on macOS and Linux (`arch -x86_64 …` is used
by Rosetta and Homebrew scripts), and `arch` on PyPI is the well-known ARCH/GARCH econometrics package,
with import name `arch`. The working name stays for now; it needs a decision before any public release.
