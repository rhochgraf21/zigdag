# working with zigdag

This is how to work in a project that `zigdag` keeps. It's less about the commands (there are only a few) and more about a handful of ideas. Once you have those the commands mostly explain themselves.

The examples come from one small shop project. 

## customer needs 

A lot of code is perfectly well built, but isn't quite what someone needed. Agents are especially prone to this, since a request usually arrives as a solution ("add a cache") and they will happily build exactly that (and maybe a few things unsaid). The need behind the request (who is waiting, and on what) stays in your head... and learning a customer's needs from source code is hard, usually.

So the design in `zigdag` starts all the way at the top, with customer needs. `design/customer.yaml` says who the system is for, what they're trying to get done (a job), and how they'd judge whether it went well (outcomes). There is no product in it yet.

```yaml
buy-products:
  job: Buy a product online
  performer: Shopper
  outcomes:
    wrong-charge: Minimize the likelihood that a shopper is charged the wrong amount
```

What the system must do comes next, in `design/functional.yaml`, and each top-level requirement says which outcome it `serves`:

```yaml
shop.billing:
  serves: [buy-products.wrong-charge]
  statements:
    charge: The billing shall charge a shopper the price of each product.

shop.billing.api:
  statements:
    price: The api shall give the price of a product in cents.
    unknown: If a product has no price, then the api shall refuse the product.
```

From there it goes back and forth: a requirement gets a part of the code that does it (billing is `shop/billing/`, and the names match on purpose), that part gives rise to smaller requirements of its own (the api, the rates), and those get their own parts, down to modules and data types. This is the zigzag in `zigdag` (the DAG is that parts on one level can't depend on each other in a circle, which `zigdag show` draws for you). (oops, this might be the inspiration for the name zigdag...)

`zigdag` checks that the chain is there, so a requirement that serves nobody, or a module that belongs to no requirement, shows up. It can't check that the need itself is *right*. For that it can ask a fresh agent to critique the design (`zigdag critique`), and the decision stays with a person.

Of course, on an existing codebase the code is already there, so you come at it from the other end: `zigdag init` guesses the parts from your code and you fill in the top afterwards. You don't have to write it all on day one, since whatever is missing is a thing to do and `zigdag next` lists it.

## global structure, made local

A lot of what makes a codebase good is global. "Billing has no side effects." "Web doesn't reach into billing's internals." "Every module is there for a reason." These are true of the whole system (or you hope they are), and help make sure the system you're building stays stable. But the source code holds them only implicitly, which is one theory for why agents tend to wreck them.

`zigdag` has you write each of these down in `design/`, on the part of the code it is about:

```yaml
billing-effects:
  on: shop.billing
  serves: [maintain.unrelated-breakage]
  check: effects
  with:
    allow: []
```

Now it's local, so it can be managed more carefully and closely, an agent can be handed it, and whether the code follows it becomes more deterministic and less art.

When you or your agent is about to change a file, `zigdag context` gives the local view of all of this for that one file:

```console
$ zigdag context src/shop/billing/api.py
shop.billing.api: The api shall give the price of a product in cents.

  why it exists:
    Shopper wants to: Buy a product online
      Minimize the likelihood that a shopper is charged the wrong amount
    through: shop.billing.api ← shop.billing ← shop

  it must:
    The api shall give the price of a product in cents.  [passing]
    If a product has no price, then the api shall refuse the product.  [to do]

  limits:
    The billing shall depend only on deal.
    The billing shall have no side effects.
```

## a checker that pushes

`zigdag check` is in some limited ways analogous to a borrow checker. You don't learn Rust's ownership rules up front and then apply them perfectly. You write code, the checker pushes back, and after a while you write code the way it wants, because that way turns out to be better *practices*. `zigdag` does this for your agent, at the level of the design.

For example, there is a rule that effectful code cannot have business logic. Nobody has to explain the functional core, imperative shell pattern to the agent. It writes a function that works out a price and prints it, and gets this (from one of zigdag's own test projects):

```console
src/tiny/cli.py:13:32: break[planned-effects] tiny.cli.main: tiny.cli.main passes `str(price(order))` to a
call, and it is neither a plan value nor its own parameter: hand it to a pure function, and pass what that
function returns
```

So it moves the working-out into a function with no side effects, and what is left only carries the result out:

```python
@deal.pure
def bill(order: Order) -> Bill:          # prices, discounts and tax: the business logic
    ...

def checkout(order: Order) -> Receipt:   # the effects, and no decisions
    the_bill = bill(order)
    bank.charge(order.card, the_bill.total)
    return Receipt(the_bill)
```

That is functional core, imperative shell, and the agent got there by following the breaks, which is the general way `zigdag` works: a rule is enforced and the pattern follows naturally. Named types between parts, and contracts on what other parts rely on, come about the same way.

When a check breaks there are two things you can do: fix the code so it fits the design, or change the design on purpose because the design was wrong. Either way, a good outcome.

## anything new fails until someone allows it

Pretty much all linters work by banning things. `zigdag` goes the other way on this choice. A part may use what its rule allows and nothing else, a new module has to be named in the design, and a new library has to be declared. So when an agent adds something nobody asked for, it doesn't slip by, it shows up as a break:

```console
src/shop/web/checkout.py:2:1: break[web-dependencies] shop.web.checkout: shop.web.checkout depends on
shop.billing.rates, which web-dependencies does not allow
```

Of course, this would be unbearable on an existing codebase, which is why `zigdag init` records what your code does today as what is allowed. The first check passes, and from then on anything new is a decision.

## what can be checked, and what can't

`zigdag check` only reads. It never runs your code, it gives the same answer for the same files, and it is quick. Everything above is that kind of check.

Some things can't be checked by reading, for example "did my agents write bad tests". For those `zigdag` has test-time checks. `zigdag test` runs your tests and watches what the code does while they run, so a test that claims to verify billing and never runs billing is caught. It runs contract tests (your contracts, on generated inputs). And it runs mutation tests, which make small wrong versions of your functions to find tests, and even contracts, that wouldn't notice if your code was wrong. This is can be handy because agents LOVE writing tests that are either weak or that copy the assumptions of the code.

A test says which statement of the design it verifies:

```python
@verifies("shop.billing.api#price")
def test_tea_costs_four_fifty():
    assert price(Product("tea")) == 450
```

`zigdag ready` does the check and the tests together and gives one answer, which is what you want before a PR:

```console
$ zigdag ready
tests/test_billing.py .                                                  [100%]
zigdag: running the contracts of 1 functions on generated inputs
zigdag: mutants 1/1 shop.billing.api.price: 1 made, judged by 1 tests: 1 killed

0 breaks, 0 questions, 0 results out of date, 7 things to do

ready: yes
```

## what it tells you

`zigdag` doesn't have warning levels. A break means the code contradicts the design. A question means it couldn't tell, and you answer it once with a reason (`zigdag answer`), which sticks until that code changes. Out of date means the tests ran against older code, so run them again. And a thing to do is something the design says that isn't built or tested yet. This never fails anything, since you're allowed to (and are highly highly recommended to) write the design before the code.

## debt you can see

Any rule can be silenced for a piece of code by listing it under the rule's `except`, with the reason next to it:

```yaml
max-lines:
  except:
    - cli.plans  # 1,033 lines: every command's decisions in one file; splitting it by command is planned
```

That's how `init` records the problems you already have. It helps you go after debt, or explicitly silence it (which means it is recorded). Taking one line off an `except` list makes a good small PR.

## decisions before code

A PR that changes how the system is built changes the design, and `zigdag review main` shows that first, as a sentence:

```console
$ zigdag review main
functional
  ~ constraint web-dependencies  [not critiqued; not approved]
      rule: "The web shall depend only on the standard library." → "The web shall depend only on api."
```

So a reviewer sees the decision the PR made before reading how it was carried out.

## when something gets through

Sometimes a problem gets past every check and a person finds it. The idea borrowed from Jidoka is that you don't only fix the problem, you update the process that missed it, or at the very least check for it automatically. In `zigdag` that usually means a rule. If it's a practice of your own that no tool knows about, write it as a plain Python function in `design/checks/`:

```python
from zigdag.checks import broken

def short_modules(context, rule, *, lines: int = 300):
    """Each module is short enough to read in one sitting."""
    for path, unit in context.model.units.items():
        if unit.size > lines and context.in_scope(rule, context.tree.unit_owner.get(path)):
            yield broken(rule, path, unit.span, f"{path} is {unit.size} lines; at most {lines}")
```

From then on it is checked like any other rule. And if you notice something outside what you're working on, `zigdag raise` puts it on the record, so it isn't lost. ]

## more about rules

[rules.md](rules.md) lists the rules `zigdag` comes with.
