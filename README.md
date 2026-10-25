# arch

Design-as-code for humans and coding agents.

arch keeps a project's intent and structure in plain-text files next to its code. It checks the code
against them, gives agents the context they need, and helps people review what agents produce.

> **Status:** early. Python is the only language supported today. arch maintains its own design with
> itself, in [`design/`](design/).

## Why

In traditional agentic coding, we've all seen the same problems appear as a project grows. This is how
arch helps with each of them.

**Agents lose the big picture.** An agent reads a few files, guesses what the system is for, and writes
code that works but fits badly. arch gives it a context card for the part it is changing. The card holds
the part's purpose, the needs behind it, its acceptance criteria, the rules in force and its neighbours'
interfaces, all within a token budget.

**Boundaries erode.** Each convenient import looks harmless, until the system is hard to change. arch
records which parts may use which, and `arch check` fails on the line that crosses a boundary.

**Side effects creep in.** A function that only computed starts reading files or calling the network,
and nobody notices until something breaks. arch infers each function's effects, such as network, file,
environment and clock access, both directly and through the functions it calls. A constraint can keep a
part pure, or allow it only the effects it needs.

**Abstractions go bad.** Agents tend to add thin wrappers, flag parameters and interfaces with a single
implementation. arch asks every part to name the decision it hides or the vocabulary it publishes. It
flags shallow parts that show many names with little code behind them, and functions whose parameters
pick their behaviour. `arch split` makes giving a second function its own part as easy as bolting it
onto the first.

**Design thinking stays shallow.** Asked for a design, an agent usually takes the first idea that works.
arch's design matrix shows where parts are coupled, and `arch next` names the method for each problem.
The methods teach agents to interview for needs, to write requirements in EARS form, and to resolve
coupling with TRIZ separation and ASIT's rule of using what is already there. Independent critics then
judge the design against a rubric, and arch keeps only the findings that quote the text.

**Performance slips.** Tests pass while latency doubles, because nothing states what fast enough means.
A constraint in arch can set performance budgets, such as a p95 latency, and a sub-part can tighten a
budget but never loosen it. Measuring code against those budgets is not built yet.

**Review cannot keep up.** Agents write more code than anyone can read line by line. `arch review`
presents a change in the order a reviewer needs it: intent, design and structure first, then the code
ranked by risk.

**People lose track of their own system.** After months of agent changes, nobody can say how the parts
fit together. arch keeps the design in short files that people can read, and draws it as outlines,
diagrams and matrices at any depth. Reviews explain each change in the design's own terms before they
show the code.

**Standards live only in people's heads.** Rules such as "the core never touches the network" are easy
to state and easy to forget. In arch, they are constraints: plain files whose rules the check enforces
on every change. Requirements are linted against EARS and INCOSE wording rules, and a part's status can
rise only when nothing is open at the stages it claims.

For example, this is what an agent sees when a pure part starts calling the network, and when one part
reaches into another part's internals:

```console
$ arch check
error   C008 shop.billing.api: shop.billing.api.charge has effect network (directly), which is not allowed here (allowed: none) (src/shop/billing/api.py:5)
        hint: move the effect behind a shell component and pass data in, or change the constraint (with a decision entry)
error   C001 shop.web.checkout: shop.web.checkout imports shop.billing.rates (component shop.billing.rates), which is not among its uses (src/shop/web/checkout.py:2)
        hint: add it to the uses of shop.web.checkout (if its parent may use it), or remove the import
2 errors, 0 warnings, 24 info (--all to list the rest)
```

## Install

arch needs Python 3.11 or later. It is not on PyPI yet, so install it from a clone of this repository:

```sh
uv tool install .            # or: pip install .
uv tool install ".[mcp]"     # also installs the MCP server for agents
```

## Quick start

```sh
cd your-project
arch init             # draft a design from the code you already have
arch check            # passes at first: today's problems are accepted, and only new ones fail
arch agent install    # teach your coding agent to use arch (Claude Code, or --agent generic)
```

## The main commands

arch aims to be a deep module itself: a few commands in front of a lot of machinery. Most work needs
only these.

| Command | What it gives you |
|---|---|
| `arch init` | A draft design inferred from existing code, with today's problems accepted as a baseline. |
| `arch context <part or file:line>` | The context card for one part, sized for an agent's prompt. |
| `arch check` | Departures from the design, such as crossed boundaries, forbidden effects, untested criteria and unclear requirements. |
| `arch next` | The most valuable next actions, each with the command or method to use. |
| `arch review [base]` | A change summarised for review. With `--serve`, it becomes local web pages to step through. |
| `arch critique` | A request for an independent critic, usually a fresh agent, to judge design text against a rubric. |
| `arch mcp` | Every operation as an MCP tool, so agents can call arch directly. |

The editing commands (`add`, `set`, `link`, `move`, `split` and `remove`) change design files with
minimal diffs. Run `arch --help` for the full list.

## What a design looks like

A design is a tree of components. Each one is a short Markdown file with YAML frontmatter:

```markdown
---
kind: component
realizes: Charge customers for their orders
solution: A payment API over a provider client, with rates kept private
hides: How rates are computed and which provider is used
uses: [orders]
exports: [api]
status: specified
---
## Acceptance criteria
- AC1: When a charge fails, billing shall leave the order unpaid and report why.
```

Tests link to criteria with `@realizes("shop.billing#AC1")`, so every requirement points to its
evidence.

Standards are constraints, written the same way. This one keeps billing pure:

```markdown
---
kind: constraint
applies_to: [shop.billing]
rule:
  effects:
    allow: []
---
Billing takes data in and returns data. Input and output belong to the shell.
```

## Learn more

- [DESIGN.md](DESIGN.md) explains the ideas behind arch, the decisions taken, and the ones rejected.
- [design/](design/README.md) is arch's own design, maintained with arch.
