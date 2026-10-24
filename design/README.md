# The design of arch, kept with arch

This directory is the axiomatic design of `arch`, in the format `arch` reads. It is edited with arch's
own commands and checked by `arch check` (which must stay at zero errors and zero warnings). Nothing
here is derived by hand any more: run the commands below for the current picture.

```
design/
  needs/          customer needs: what must be true for stakeholders, solution-neutral
  constraints/    policies inherited down the tree, mostly machine-checked (effects, imports, port types)
  components/     the FR/DP hierarchy; the directory tree is the decomposition; decisions live on components
  baseline        findings accepted as a starting point (empty for arch itself)
```

Three node kinds match axiomatic design's domains: needs (customer domain), components (a functional
requirement and the design parameter chosen for it), constraints. A decision is the choice of a design
parameter, so it lives on the component it shaped.

## How to read a component

```yaml
realizes: <functional requirement: what it must do>      # the FR, one function
solution: <design parameter: how, at this level>          # the DP
hides:    <the decision it encapsulates (Parnas secret)>
uses:     [<siblings or exported parts it may depend on>]  # = design-matrix row = allowed imports
exports:  [<children visible outside it>]                  # default: none
accepts_coupling: [[<child>, <child>]]                     # couplings kept on purpose (with a decision)
serves:   [<needs>]                                        # top level; children inherit
status:   draft | specified | contracted | verified        # checks tighten as this rises
suppress: {RULE: reason}                                   # accepted findings, with the reason
```

The body holds acceptance criteria (`- ACn:` lines in EARS form, linked from tests with
`@realizes("component#ACn")`), optional rationale, and a `## Decisions` section: one `### title` per
choice with `- Chose:` and `- Because:` lines (plus `Over:`, `Consequences:`, `Previously:`,
`Backed by:`). References are written short and resolve by lexical scope. Interfaces and contracts live
in code; arch reads them back.

## Seeing the design

| To see | Run |
|---|---|
| The decomposition, in build order | `arch outline [component] --depth N` |
| A design matrix, or declared vs. observed coupling | `arch matrix <component> [--observed]` |
| Build layers, or the impact of a change | `arch plan [component...]` |
| Everything needed to work on one part | `arch context <component | path[:line]>` |
| What to do next | `arch next [component]` |
| How the design changed | `arch diff [revision]` |
| Whether design and code agree | `arch check [--all]` |

## Open questions

1. **Acceptance criteria as lines or nodes?** Lines in the component body (current) are compact;
   separate nodes would allow richer links (one criterion to many tests) at the cost of many more files.
2. **Non-code coupling.** `uses` covers code dependencies only. Shared databases, timing and ordering
   couple components too. A field of its own, or always an `accepts_coupling` entry with a decision?
3. **Budget composition.** Child budgets ≤ parent is checked; latency along call chains is not yet
   specified.
4. **Cross-repository composition.** How a parent design references a versioned sub-design from another
   repo (the multi-repo / Terraform-module story). Leaning toward `uses: [pkg:billing@2]`, against
   that package's published external spec.
5. **EARS strictness.** `S103` is a warning even at `contracted`; should it become an error there?
6. **CLI library.** Standard-library argparse for now (no dependency; hidden behind `integrate.cli`).
7. **Second adapter.** TypeScript (semantic) proves the fact schema is neutral; Mojo via tree-sitter
   (structural) is the exciting one. Both wait until the Python path is proven.
8. **Name.** `arch` collides with `/usr/bin/arch` and with the `arch` package on PyPI (see DESIGN.md §13).
