# arch

Design-as-code for humans and coding agents.

arch keeps a project's intent and structure in plain-text files next to its code. It checks the code
against them, gives agents the context they need, and helps people review what agents produce.

> **Status:** early. Python is the only language supported today. arch maintains its own design with
> itself, in [`design/`](design/).

## Why

In traditional agentic coding, we've all watched an agent lose the big picture. It reads a few files,
guesses what the system is for, and writes code that works but fits badly. arch gives an agent a
context card for the part it is changing. The card holds what the part is for, the needs behind it,
its acceptance criteria, the rules in force, and the interfaces of its neighbours, all within a token
budget.

We've also seen boundaries erode one convenient import at a time, until the system is hard to change.
arch records which parts may use which, and `arch check` fails on the line that crosses a boundary.

Finally, agents write more code than anyone can review line by line. `arch review` presents a change
in the order a reviewer needs it: intent, design and structure first, then the code ranked by risk.

For example, this is what an agent sees after it reaches into another part's internals:

```console
$ arch check
error   C001 shop.web.checkout: shop.web.checkout imports shop.billing.rates (component shop.billing.rates), which is not among its uses (src/shop/web/checkout.py:2)
        hint: add it to the uses of shop.web.checkout (if its parent may use it), or remove the import
1 error, 0 warnings, 24 info (--all to list the rest)
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

## Learn more

- [DESIGN.md](DESIGN.md) explains the ideas behind arch, the decisions taken, and the ones rejected.
- [design/](design/README.md) is arch's own design, maintained with arch.
