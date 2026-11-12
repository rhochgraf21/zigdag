# the flow

This is what a change looks like with `zigdag`, start to finish. First with one agent. Then with many agents at once, each building one part.

The examples use the small shop project from [practices.md](practices.md).

## one agent

**0. Once per project**

```sh
zigdag init --default        # drafts a design from your code, in design/
zigdag check                 # passes: today's problems are accepted as a baseline
zigdag agent install claude  # adds zigdag's skills and hooks to Claude Code
```

**1. You ask for what you want**

The session starts with the design in view. You don't have to explain the architecture again.

**2. The agent finds where it is**

`zigdag next` lists what is to do, in the order the design matrix allows:

```console
$ zigdag next
1 things to do, in the order the design matrix allows:
  shop.billing.api#unknown: no test verifies shop.billing.api#unknown
```

`zigdag context` gives the local view for one file or one part: why it exists, what it must do, its limits, what it uses, and what is open there.

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

**3. The design changes first**

If the change is a new decision (a new requirement, a new part, a new dependency), the agent writes it in `design/` before the code. Whatever the design now says that isn't built shows up as a thing to do. `zigdag critique` asks a fresh agent to critique the changed entries.

**4. The agent writes the code**

When it finishes a turn, `zigdag` tells it what it broke. `zigdag check` gives the same answer on demand:

```console
$ zigdag check
src/shop/web/checkout.py:2:1: break[web-dependencies] shop.web.checkout: shop.web.checkout depends on
shop.billing.rates, which web-dependencies does not allow
```

There are two ways out of a break: fix the code so it fits the design, or change the design on purpose.

**5. Every statement gets a test**

```python
@verifies("shop.billing.api#unknown")
def test_a_product_with_no_price_is_refused():
    ...
```

`zigdag test` runs the tests while watching what the code does, then the contracts on generated inputs, then the mutation tests.

**6. One answer**

```console
$ zigdag ready
0 breaks, 0 questions, 0 results out of date, 7 things to do

ready: yes
```

**7. You review the decision, then the code**

```console
$ zigdag review main
functional
  ~ constraint web-dependencies  [not critiqued; not approved]
      rule: "The web shall depend only on the standard library." → "The web shall depend only on api."
```

A person approves each changed design entry with `zigdag approve`.

**8. When something gets through**

If a person finds a problem that no check found, `zigdag raise` puts it on the record. It is answered together with the rule or statement that will catch it next time.

**Who does what**

- **You:** say what you want, steer the design, approve it, review the result.
- **The agent:** design, code and tests, following the breaks.
- **zigdag:** gives the context, checks the code against the design, says ready or not.

## many agents

A larger change touches several parts. The design matrix already says how the parts depend on each other, so it can say which work can go on at the same time. One agent, the chief, coordinates the others. `zigdag work` tells the chief what is ready.

`zigdag` does not start agents. It answers, and the chief acts on the answers.

The example: prices should take a discount. That touches pricing and checkout.

**1. Design, with you**

You and the chief settle what's wanted. The chief notes the commit the change begins at (here `4f2a91c`), then edits `design/` and writes what the parts share: changed structures, and new names with their parameters and what they return. It only adds. Nothing old is removed yet, so everything still passes.

You read `zigdag review 4f2a91c` and approve. The chief commits.

**2. The chief asks for work**

```console
$ zigdag work --base 4f2a91c
build shop.pricing
  on part/shop.pricing, which lands on main
  what to build: zigdag context shop.pricing --base 4f2a91c
  built when: zigdag ready --base 4f2a91c says yes, or built
$ zigdag work --base 4f2a91c
build shop.checkout
  ...
$ zigdag work --base 4f2a91c
wait: 2 parts being built: shop.checkout, shop.pricing
```

Handing a part out makes its branch, `part/shop.pricing`, so the next answer is a different part. Checkout uses pricing, and still they are built at the same time: checkout is built against what step 1 settled.

The chief starts one agent per part, each in its own folder (`git worktree add ../shop.pricing part/shop.pricing`), and gives it the lines under `build`.

**3. An agent builds**

It runs the first command it was given:

```console
$ zigdag context shop.pricing --base 4f2a91c
shop.pricing: The pricing shall give the price of a product in cents after the discount of the product.
  code: shop.pricing

  changed since 4f2a91c:
    ~ FR shop.pricing
        statements price: "The pricing shall give the price of a product in cents." → "The pricing shall give the price of a product in cents after the discount of the product."

  asked, and not given yet:
    shop.pricing#price: needs a test of what it says now: The pricing shall give the price of a product in cents after the discount of the product.

  why it exists:
    ...
```

It writes code and tests inside its part. It stops when `zigdag ready --base 4f2a91c` ends with one of two lines:

```console
ready: yes
```

```console
built: waiting on shop.pricing to land
```

Anything else means it isn't finished. On a part's branch, `ready` breaks when the branch changed a file that isn't the part's code, a test or the log, and when it changed what other parts use of the part: a name's parameters, what it returns, its fields.

**4. The chief asks again**

```console
$ zigdag work --base 4f2a91c
land shop.pricing
  bring part/shop.pricing up to date with main, then: zigdag ready --base 4f2a91c
  on yes, merge part/shop.pricing into main
```

When a part is built but its tests need a part that hasn't landed:

```console
$ zigdag work --base 4f2a91c
wait: shop.checkout is built, and needs shop.pricing to land
```

**5. An agent lands a part**

A fresh agent, in the part's folder. It merges main into the branch and runs `zigdag ready` again. On a yes, it merges the branch into main. If a test now fails against the real thing, it fixes that inside the part, using the part's context and the failure.

Once pricing has landed, the next answer is `land shop.checkout`.

**6. If the design is wrong**

An agent that finds the design wrong doesn't change it. It raises a question and stops:

```console
$ zigdag raise question shop.pricing "is a discount per product?" --by agent
```

```console
$ zigdag work --base 4f2a91c
blocked: question on shop.pricing, raised from shop.checkout: is a discount per product?
  stopped: shop.checkout
  when it is settled: zigdag answer 5c0de1f2a9b84d37 <answer> <why> --by <who>, in the folder of shop.checkout
```

The chief stops the agents named and comes to you. Parts the question doesn't concern are listed as continuing. While it stands, nothing new is handed out. You decide. If the design changes, the chief amends it on main, you approve, and the chief commits. Then the question is answered, in the folder it was raised in.

A part whose branch is now behind a design change that concerns it is handed out again:

```console
$ zigdag work --base 4f2a91c
build shop.checkout
  the design changed where it lands since its branch last had it: bring the branch up to date first
  ...
```

**7. Closing**

```console
$ zigdag work --base 4f2a91c
done
```

The chief removes what the change replaced. You read the final `zigdag review 4f2a91c`.

**Who does what**

- **You:** approve the design, answer blocked questions, read the result.
- **The chief:** asks, hands on what it was told, stops agents when told. It doesn't build, land or remember.
- **An agent:** one part, one task, with its context from `zigdag`.
- **zigdag:** says what's ready, what's allowed, and who must stop.

### the five answers

- **build** or **land**: a part, and which of the two.
- **wait**: work remains, and all of it is someone's already, or waits for something that is. It says what.
- **blocked**: work remains, and waiting won't help. Someone has to act. The command exits 1.
- **done**: the change asks nothing more.

Wait and blocked are apart on purpose. A chief that waits on something that will never clear is how this kind of scheme hangs.

### why it is shaped this way

**Design before code.** The design delta says which parts changed, so nobody declares the work separately. And since `design/` is settled before any building starts, the agents only read it and never collide on it.

**What the parts share is settled first.** "Row depends on column" means row depends on what column offers: its structures, and its names with their parameters. Once those are written, row and column can be built at the same time. This is where the concurrency comes from.

**One agent per part.** A lock has to be something you can name before the work starts and check after it ends. Lines can't be named ahead of time. Files can, but they are the wrong boundary: what breaks is one agent changing a shape another relied on, not two agents editing nearby text. A part can be named, and the check can hold an agent inside it.

**The order comes from the tests.** There is no rule that says what must land first. A part lands when `zigdag ready` says yes on a branch that is up to date with main. If its tests need the real pricing, they fail until pricing lands.

**Nobody remembers.** Each call to `zigdag work` reads the design, the code, the branches and the log as they are, and works out the answer again. Nothing is stored, so nothing goes stale when the design is amended. A chief or an agent can be replaced by a fresh one that just asks again.

**No tickets.** What to do, why, what not to touch, and when it's done are all in the design already. A ticket would be a second copy that goes out of date.

### what it costs

- An agent may keep building for a short while on a design that is about to change, between the question being raised and the chief's next call.
- While a question is open, nothing new is handed out, even to parts it doesn't concern. Parts already being built go on.
- The design matrix is read from the code. A new part with empty bodies calls nothing, so what it waits on is only known once its branch has code.
- A branch shows that a part is taken. Nothing shows that a landing is under way, so `land` is said until the part has landed, and the chief must not hand the same landing on twice.
- If an agent dies holding a part, `zigdag` can't tell. The chief knows which agents are alive, and deletes the dead one's branch.
- The design step has to be committed before anything is handed out, and `zigdag work` is asked from the branch the parts land on.

### a changed statement is work, with one agent too

A statement that changes while its tests stay as they were is a thing to do, whenever there is a base to compare with: `zigdag check --base main` lists it, and `zigdag ready --base main` says no. The old test passed for the old sentence. It says nothing of the new one.
