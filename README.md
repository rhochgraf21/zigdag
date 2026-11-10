# zigdag

`zigdag` is for devs who want to manage a large codebase with agents, without all the effort.

It gets agents to write better code, by following... the design.

Finally, you can be sure agents are following your practices and architecture.

## why

If you use coding agents, you know the feeling of starting a project. For the first couple of days, you're flying. Then you open your editor and find the internals are a mess... sometimes even though you were watching the PRs.

Why does this happen? One theory is that coding agents make great *local* changes, but what you wanted was a well-built whole. Source code holds architecture & process choices only implicitly. This is hard for agents to reason about, and to regather every session.

The idea of `zigdag` is simple: make global structure local. `zigdag` puts the design of your system in version-controlled files (in `design/`). It uses them to give agents design context, deterministically check that PRs meet the design, and reduce the complexity of reviewing PRs (especially when it comes to design). Your agent can access it through skills.

`zigdag` has checks that push your agent towards better code (just like a borrow checker does for devs). For example, it can enforce a rule that effectful code cannot have business logic, naturally leading to the functional core, imperative shell pattern. For that which can't be checked, for example "did my agents write bad tests", `zigdag` can provide test-time checks: for example, `zigdag test` runs your tests, contract tests, and mutation tests (to find bad tests and even bad contracts).

## install

Set it up once per project:

```sh
pip install .                # from a clone of this repo, into your project's environment
cd your-project
zigdag init --default        # drafts a design from your code, in design/
zigdag check                 # passes: today's problems are accepted as a baseline
zigdag agent install claude  # adds zigdag's skills and hooks to Claude Code
```

Then work with your agent as usual. With Claude Code, each session starts with the design in view, and when the agent finishes a turn, zigdag tells the agent what it broke.

Your part:

1. Steer the designs. `zigdag init` guesses. In `design/`, correct what each part is for and what it may use.
   `zigdag show` shows the tree.
2. Ask for what you want. Your agent will use zigdag as it makes its PR.
3. Review PRs. `zigdag review main` shows what changed in the design, then what the change broke.
   `zigdag ready` says whether the PR is ready, yes or no.

## example

Start from an existing project:

```console
$ zigdag init --default
wrote zigdag.toml
wrote design/functional.yaml
wrote design/process.yaml
wrote design/customer.yaml

$ zigdag show
shop: (no function written yet)
  children:
    billing: (no function written yet)  (shop.billing)
    web: (no function written yet)  (shop.web)
```

`zigdag init` wrote down what each part uses today. Web uses nothing from billing:

```yaml
web-dependencies:  # what shop.web depends on today, recorded by zigdag init
  on: shop.web
  check: may-depend-on
  with:
    allow: []
```

Later, an agent working on checkout reaches into billing for the rates. zigdag stops it:

```console
$ zigdag check
src/shop/web/checkout.py:2:1: break[web-dependencies] shop.web.checkout: shop.web.checkout depends on
shop.billing.rates, which web-dependencies does not allow
```

The agent moves the rate lookup into billing, where it belongs, and records the new dependency (`allow: [shop.billing.api]`). zigdag also has it write a contract for the new function, since web now relies on it.

```console
$ zigdag check
0 breaks, 0 questions, 0 results out of date, 9 things to do
```

At review, `zigdag review main` shows that web now uses billing's api, before any code:

```console
$ zigdag review main
functional
  ~ constraint web-dependencies  [not critiqued; not approved]
      rule: "The web shall depend only on the standard library." → "The web shall depend only on api."
```

## philosophy

`zigdag` makes global structure local. It guides the design of your application through a philosophy that borrows a mix of axiomatic design, architecture-as-code, EARS, INCOSE, TRIZ, ASIT, and Jidoka. (You don't need to know any of these. zigdag teaches the methods to your agent.) The design lives in plain files on disk, and `zigdag` provides utilities to help agents get the right context for what they're building. Better, `zigdag check` verifies that the implementation truly matches the design, so you know the code still fits what you intended.

### ideas borrowed

- Each requirement gets its own part, so changing one doesn't disturb another (Suh).
- Each part hides a decision likely to change (Parnas).
- The design is viewable at any zoom, from the whole system down to one part (C4 Architecture as Code).
- Requirements are precise enough to test (EARS, INCOSE).
- Promises are written as contracts (Meyer).
- Conflicts between requirements are resolved, not traded off (TRIZ), ideally with what the system already has (ASIT).
- When a defect escapes, you update the process that missed it (Jidoka).

## learn more

[docs/practices.md](docs/practices.md) teaches how to work with zigdag, start to finish, on one small example.

Every rule is listed in [docs/rules.md](docs/rules.md). `zigdag checks` prints the same list. You can add your own as plain Python functions in `design/checks/`.
