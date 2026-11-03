# archform: the model

archform keeps a software system's design as a record that is checked against the code. The record
follows axiomatic design's four domains. Every term has one definition. Every statement has a grammar.
Every check gives the same answer for the same record and code.

This file describes the model and the record. It does not describe how archform is built.

Status: proposal.

---

## 1. Principles

1. **Every term is defined once,** and nothing outside this file adds meaning to it.
2. **Every field is necessary.** A field stays only if a check needs it, or if it records something the
   code cannot show.
3. **Written, worked out, or checked.** Everything in the model is one of these:
   - **written:** a sentence with a grammar, or a value with a type;
   - **worked out:** derived by archform from what is written plus the code;
   - **checked:** a link that archform verifies.

   Anything that fits none of these is judgement, for a critic or a person. Otherwise it is not in the
   model.
4. **Simple to write, deep underneath.** People write few, plain things. archform does the heavy work.
5. **Nothing can be left out by accident** (the closed world):
   - **By position, never by list.** A rule placed on a name covers everything below that name,
     including what is added later.
   - **Allow-lists, never deny-lists.** Anything new fails until someone allows it.
   - **Closed vocabularies.** Effects, check kinds, metrics and gates come from fixed lists. An unknown
     word is an error, never ignored.
   - **Structure in, sentence out.** A rule archform enforces is written as structure, and archform
     writes its sentence. Enforcement is never guessed from prose.
   - **Only tighten going down.** Nothing below a rule can loosen it. Only the rule itself grants
     exceptions.
   - **Total coverage.** Everything the adapters find belongs to exactly one design parameter: every
     module, deployed resource and table. Every FR statement needs evidence. Every constraint is either
     checked by archform or verified by evidence.
6. **Every check has one of four results.** There are no warning levels:

   | Result | Meaning |
   |---|---|
   | **holds** | nothing to report |
   | **breaks** | the code or the record contradicts the record. This is an error. |
   | **to do** | something written is not built or evidenced yet, for example an FR with no code, or a statement with no test. Never an error. `archform next` lists these. |
   | **question** | archform is unsure, either because it could not analyse something (dynamic imports, `eval`, an untraceable resource name) or because the check is a guess. A question is answered once in the log and stays answered until what it is about changes. It is never treated as a pass. |

   - Known breaks are listed under the rule's `except`.
   - A check that fails to run breaks. It is never skipped.
7. **The core is free.** The checks every project needs are built in and on without anyone writing
   them (§4.4, §4.5). The record holds only what is particular to the project. Built-in rules can be
   tuned, and known breaks can be excepted. Turning one off is a visible, reviewed entry.
8. **Language-free model, language-specific adapters.** Nothing in the record depends on a language.
   Adapters (§5) read each language or tool into one code model, and every check works on that model.

---

## 2. The four domains

```
 CUSTOMER            FUNCTIONAL              PHYSICAL             PROCESS
 Job                 FRs                     Design parameters    Process variables
 Outcomes      ──►   Constraints       ──►   system, containers,  (how we make and
 (what they          (what it must do,        components,     ──►  check it)
  want done)          and the limits)         structures                │
                          ▲        zigzag         │                     ▼
                          └───────────────────────┘                   code
```

### 2.1 Customer domain

| Term | Definition |
|---|---|
| **Job** | What someone is trying to get done, with no product in it. |
| **Performer** | Who does the job. |
| **Outcome** | A measure the performer uses to judge whether the job went well. |
| **Customer attribute** | *Worked out:* an outcome the product commits to, meaning one that some FR or constraint serves. |

**The maintainer job is built in.** Every system has a second job besides its users' job: changing
the code without breaking it. The performer is a person or an agent. Its outcomes give code-quality
rules a reason to exist:

| Outcome | Statement |
|---|---|
| `maintain.find-code` | Minimize the time it takes to find the code that performs a function |
| `maintain.unrelated-breakage` | Minimize the likelihood that a change breaks an unrelated function |
| `maintain.review-time` | Minimize the time it takes to review a change |

A project may add outcomes to `maintain`. The built-in constraints and process variables (§4.4) serve
these outcomes.

### 2.2 Functional domain

| Term | Definition |
|---|---|
| **FR** (functional requirement) | One function the product must perform, written as EARS statements. Exactly one statement is ubiquitous and states the function. The rest add triggers, states or conditions. |
| **Statement** | One EARS sentence, named, so evidence can point at it. |
| **Constraint** | A limit on which designs are acceptable, placed on one FR and covering everything below it. It is enforced in one of two ways: a **check** that archform runs, or a **statement** verified by evidence. |

**FRs form a tree.** The root FR is the system. Each DP gives rise to the FRs one level below it (the
zigzag).

**Which domain does a rule belong to?**
- If it is visible at a DP's edge, it is a **constraint**. Examples: what the DP does, which effects
  it has, what it depends on.
- If it is about how the code inside is written, checked or produced, it is a **process variable**.

### 2.3 Physical domain

| Term | Definition |
|---|---|
| **Design parameter (DP)** | What was chosen to perform one FR. A DP has the same name as its FR, and is the code, resources or schema that perform it. |

**DPs form one tree with four levels.** A DP's level is worked out from what it maps to (§7.5):

| Level | Is | Maps to | Its interface | Relationships between DPs at this level |
|---|---|---|---|---|
| **System** | the root, with its context | the whole project | what the performers and outside systems see | |
| **Container** | a separately deployed unit that runs code or stores data: a service, a browser app, a worker, a CLI, a database, a bucket, a queue | deployed resources (§5.3), plus the code deployed into it | its endpoints, queues and stored data | network calls, messages, reads and writes of data containers, permissions |
| **Component** | a logical grouping of functionality behind an interface, inside one container | modules, packages, classes | its public names | imports, calls |
| **Structure** | a data type or a stored schema | types (classes, structs, enums), tables | its public fields and operations | contains, refers to, produces, consumes, changes |

**Rules for the levels:**
- **Levels nest in order:** system, then containers, then components, then structures. A structure may
  contain structures.
- **A DP with no code of its own is a grouping.** It takes the level of its children.
- **A project that describes no deployment has one implicit container:** the system itself. A project
  that is a library is one implicit container too; it runs inside its users' containers.
- **Every component belongs to exactly one container.** The exception is a component placed directly
  under the system, which is a **shared component**: it is part of every container that depends on it.
- **A structure is defined** in a component's code (a type) or in a data container's schema (a table).

**Data first.** Structures are DPs like any other. An FR such as "The tree shall give every node a
source position" is performed by a structure, and its evidence is an invariant or a property test.
The design matrix's entries at the lowest level are the operations that relate structures to FRs.
Following Do and Suh's object-oriented axiomatic design, data is designed, not left to fall out of the
code.

A type only needs to be a structure if it is in the record. Other types stay inside their component.

**Worked out from the code, never written:**
- **The design matrix** at each level: FR × DP. A DP affects a sibling's FR when the sibling's code
  depends on it, through the relationships of that level.
- **Each DP's interface**, as the table above defines it.
- **Each DP's effects:** what it does, and what it reaches through calls.
- **Each component's size and depth:** implementation size against interface size.
- **Context:** the performers from the customer domain, and the outside systems the system touches
  (named effects and external resources).
- **Roles:** for example, a *controller* is a component whose public names are endpoints, and a
  *service* is a component that controllers depend on. Roles label views. Nobody writes them.

### 2.4 Relationships

| Term | Definition |
|---|---|
| **Relationship** | A directed, typed link from one DP to another. It is worked out from the code and **never written**. Each relationship has a kind from a closed list, a direction, and evidence: the code locations that create it. |

The record states what each DP must do (FRs) and what it may do (constraints). Relationships are the
facts of what the code does. Checks compare the facts with the record.

**Between structures: the data model.**

| Kind | Means | Found from |
|---|---|---|
| `contains` | A holds a B as part of itself | a field of type B |
| `refers-to` | A points at a B by its identity, without holding it | a field of B's identity type (`product: ProductId`); a foreign key |

Both have a **cardinality**, worked out from the type: one (`B`), optional (`B | None`) or many
(`list[B]`).

A structure's **identity** is the field its adapter marks as the key: a primary key, an ORM key, or a
field named `id`. Where no key is marked, `refers-to` is a guess.

**From code to data: access.**

| Kind | Means | Found from |
|---|---|---|
| `creates` | makes a new B | its constructor; `INSERT` |
| `reads` | looks at B's contents | field access; `SELECT` |
| `updates` | changes an existing B | field assignment, or a change in place seen at runtime (§4.5); `UPDATE` |
| `deletes` | removes a stored B | `DELETE`, or removal from its store |

**Between components.**

| Kind | Means | Found from |
|---|---|---|
| `imports` | A's code refers to B's code | imports |
| `calls` | A runs one of B's operations, taking, returning and raising certain types | calls, with their signatures |

**Between containers.**

| Kind | Means | Found from |
|---|---|---|
| `calls` | a request to another container's endpoint | HTTP and RPC clients, with endpoint addresses traced from settings |
| `sends` / `receives` | a message through a queue container | queue clients |
| `reads` / `writes` | access to a data container | database and storage clients: the resource effects (§3) |

**What infrastructure allows.** These are compared with the code's relationships. They are not part of
the design:

| Kind | Means |
|---|---|
| `granted` | a permission lets A read or write B |
| `reachable` | the network lets A reach B |

**The design matrix is made of relationships.** At each level, DP A depends on sibling B when changing
B could break A:
- a caller depends on what it calls;
- a structure depends on what it contains or refers to;
- code depends on the structures it creates, reads, updates or deletes.

**Queues decouple containers.** When one container sends a message and another receives it, neither
depends on the other. Both depend on the message's structure. The matrix shows the message structure as
the thing they are coupled through: a design rule, in Baldwin and Clark's sense.

**One structure, many representations.** A structure can map to several units, for example a Python
class, a TypeScript type and a SQL table (§7.5). They are representations of one structure, and
`representations-agree` (§4.1) checks that they match.

### 2.5 Process domain

| Term | Definition |
|---|---|
| **Process variable** | A choice about how DPs are made or kept right. It is placed on one DP and covers everything below it. |

| Kind | What it is | Examples |
|---|---|---|
| `code-rule` | a check on how code is written | size limits, described public names |
| `verification` | which evidence statements need | property tests for the core, benchmarks |
| `validation` | how an outcome is measured | the soundness oracle measures wrong proofs that pass |
| `build` | a step that produces code or files | generating a name list ahead of time, rendering an infrastructure plan |
| `workflow` | a gate a change must pass | critique before review, stop on error |

### 2.6 Links between domains

| Link | Matrix | Checked |
|---|---|---|
| Customer → Functional | outcome × FR/constraint | every FR on the first level below the root, every constraint and every process variable serves at least one outcome |
| Functional → Physical | design matrix, FR × DP | FRs and DPs pair one-to-one by name; the matrix has no cycle between siblings (the independence axiom); constraints hold |
| Physical → Process | process matrix, DP × process variable (worked out from `on`) | every statement has the evidence its form and the process variables in force require |
| Process → evidence | | tests pass, benchmarks are within their bounds, build outputs are current, gates were passed |
| Evidence → Customer | | a validation process variable measures an outcome |

### 2.7 What stays judgement

These are left to a critic, and then a person:
- Is the outcome real, and important to the performer?
- Is the FR the right one for its outcomes? Is the set of FRs complete?
- Is the design a good choice among the alternatives? (The information axiom.)
- Is a statement true, as opposed to well formed?

---

## 3. Effects

Effects use deal's marker names, so that a design rule and a code contract say the same thing. A
constraint allowing `read` and a Python function's `@deal.has("read")` mean the same. The names are
ideas, not Python calls; each adapter says which calls in its language perform them (§5.2).

| Effect | Allows | Python examples |
|---|---|---|
| `global` | changing state outside the function | `global`, `nonlocal` |
| `import` | loading code while running | importing inside a function |
| `io` | **group:** `read`, `write`, `stdout`, `stderr`, `stdin`, `network`, `syscall` | |
| `read` | reading a file or directory | `open` for reading, `Path.read_*` |
| `write` | creating, changing or deleting a file | `open` for writing, `os.remove` |
| `stdout` | writing to standard output | `print`, `sys.stdout` |
| `stderr` | writing to standard error | `sys.stderr` |
| `stdin` | reading standard input | `input`, `sys.stdin` |
| `network` | network communication | sockets, HTTP clients |
| `syscall` | system calls, starting programs | `subprocess`, `os` |
| `random` | randomness | `random`, `os.urandom`, `secrets` |
| `time` | reading the system time | `time.time`, `datetime.now` |
| `env` | reading environment variables. This one is archform's own; deal has no marker for it. | `os.environ`, `os.getenv` |

- `io` is the only group, and it is defined exactly as deal defines it.
- **An effect starts** in the function that calls the effectful API. archform follows calls across the
  whole project, so an effect is charged to every function and DP that reaches it.
- **Custom effects** are registered in `archform.toml` by naming the calls that perform them. Whatever
  those calls do inside is counted under the custom name only. For example, `verus.run` allows starting
  Verus but no other program. deal accepts markers it doesn't know, so custom effects work in
  `@deal.has` too.
- **Resource effects** come free with every data container: `<container>.read` and
  `<container>.write`, for example `shop.orders_db.write`. Like custom effects, they are counted under
  their own name, so allowing `network` does not allow writing to the orders database.
- **Language effects.** An adapter may add effects only its language has, for example `unsafe` for
  Rust. They join the closed vocabulary like the rest.
- When a function declares `@deal.has(...)` or `@deal.pure`, any effect archform finds that the
  markers don't cover is an error.

---

## 4. Checks

**One registry holds every check kind,** built-in and registered. Constraints and code-rule process
variables both name a check kind and give it parameters:

```yaml
check: <kind>
with: <parameters>        # validated against the kind's parameter schema
except:                   # optional
  - <code name>  # optional reason
```

Each check kind defines:
- its **name**;
- its **parameters**, each with a type and an optional default;
- **what it reads:** the record, or parts of the code model (§5.1);
- **its sentence**, which archform renders for people;
- **whether it is exact or a guess.** When an exact check fails, the result is a break. When a guess
  fails, the result is a question.

### 4.1 Built-in check kinds

| Kind | Parameters | Fails when | Exact or guess |
|---|---|---|---|
| `effects` | `allow`: list of effects | code under the name has an effect outside `allow` | exact |
| `may-depend-on` | `allow`: list of FR names and libraries | a dependency leaves the name's subtree to something not in `allow` and not in the standard library | exact |
| `encapsulation` | none | something depends on a DP other than through that DP's interface | exact |
| `container-boundaries` | none | code in one container imports a component of another container | exact |
| `data-ownership` | none | a structure is changed by code outside the component that owns it | exact when seen or when the language enforces it; otherwise a guess |
| `no-cycles` | none | siblings depend on each other in a cycle, through any relationship | exact |
| `declared-libraries` | none | code imports a third-party package the project does not declare | exact |
| `edge-types` | `bool-returns`: allowed or not (default allowed) | a type crossing a component boundary is not defined by the project (see below) | exact |
| `declared-errors` | none | an error that can leave an operation used across a component boundary is not a project-defined type, or is not declared on that operation (see below) | exact where the adapter can trace what is raised; otherwise a question |
| `representations-agree` | none | representations of one structure differ in fields, optionality, named types or references | exact |
| `messages-agree` | none | senders and receivers on one queue use different structures | exact when the queue can be traced; otherwise a question |
| `endpoints-agree` | none | a caller's request, response or error type is not a representation of the endpoint's own | exact when the endpoint can be traced; otherwise a question |
| `references-resolve` | none | a `refers-to` points at something that is not a recorded structure | exact |
| `access-sanity` | none | a stored structure is created but never read, or read but never created anywhere | guess |
| `data-flow` | `data`: list of structures and named types; `never-reaches`: list of effects | a value of a listed type can reach one of the listed effects (see below) | exact for each place it is found; otherwise a question |
| `one-writer-per-data-store` | none | more than one container writes the same data container | exact |
| `permitted-effects` | none | code has a resource effect that the infrastructure does not grant | exact |
| `least-privilege` | none | the infrastructure grants access that no code uses | guess |
| `max-lines` | `function`: count, `class`: count | a function or class is longer | exact |
| `max-children` | `count` | an FR has more children (reads the record) | exact |
| `described-names` | none | a public name has no one-line description (exact), or its description only repeats its name and type (guess) | both |
| `min-depth` | `ratio` | a component's interface is large compared with the code behind it | guess |
| `no-mode-parameters` | none | a parameter picks between behaviours, so one name holds two functions | guess |
| `narrow-parameters` | none | a parameter is wider than what the function uses of it | guess |
| `no-single-implementations` | none | an abstraction has exactly one implementation | guess |
| `co-change` | `commits`, `threshold` | DPs keep changing together in git history without one depending on the other | guess |

Examples of the sentences archform renders:
- `effects`: "The core shall have no side effects." / "…no side effects other than reading files."
- `may-depend-on`: "The emit shall depend only on semantics and models."
- `max-lines`: "Functions under mojo2verus shall be at most 200 lines."

**What `edge-types` means.** It applies to every signature one component uses from another: the
parameters, return values and fields of public functions, methods and classes. Each leaf type in that
signature must be defined by the project, in one of two ways:

| Defined as | Python | Rust | Go | TypeScript | Needs a record entry |
|---|---|---|---|---|---|
| **a recorded structure** | a class, dataclass or enum | a struct or enum | a struct type | a class or interface | yes: a DP at the structure level |
| **a named type** | `NewType` or a type alias | a newtype struct or `type` alias | a named type (`type OrderID string`) | a type alias or branded type | no |

**Not allowed to cross:**
- **standard-library types,** such as `str`, `int`, `Path` or `datetime`;
- **third-party types,** such as `lark.Tree`.

To pass one of these, the project names it first: `SourcePath = NewType("SourcePath", Path)`.

**Leaf types** are what a signature is finally made of. Standard containers and wrappers are allowed
around project-defined leaves:
- `list[Order]`, `Order | None` and `Callable[[Order], Receipt]` are fine;
- `list[str]` breaks, and so does `dict[str, Order]`, because of its `str` keys.

**One exception, which can be turned off:** a `bool` return value is allowed. A yes-or-no answer means
what the function's name says.

**Named types are the minimum, not the ideal.**
- A plain alias gives the value a name but no protection, since any `str` still fits.
- A distinct type, such as Python's `NewType`, Rust's newtype, Go's named type or a TypeScript branded
  type, also lets a type checker catch a mix-up.

**Errors are part of the interface.** Callers depend on what an operation can fail with as much as on
what it returns. So `declared-errors` holds when every error that can leave an operation used across a
component boundary is:
- **a project-defined type.** A bare `ValueError` or `KeyError` cannot cross, just as a bare `str`
  cannot;
- **declared on that operation:**

  | Python | Rust | Go | TypeScript |
  |---|---|---|---|
  | `@deal.raises(...)` | the `E` in `Result<T, E>` | a named error type or a sentinel error in the doc comment | `@throws` in the doc comment |

archform follows what can be raised through calls, as it does for effects. While tests run, an error
seen crossing a boundary that is not declared breaks.

**How `data-flow` works without solving the halting problem.** Whether arbitrary code can ever leak a
value cannot be decided in general. archform does not try. It asks a narrower question that the design
makes answerable:

1. **The protected data has its own type.** `data` names recorded structures or distinct named types,
   for example `Email = NewType("Email", str)`. A protected value can then only become plain text at a
   **release point**: a conversion such as `str(email)`, an f-string, formatting, serialising, or reading
   the value out of a distinct type.
2. **Release points can be found from the code alone.** They are places in the text, so finding them
   needs no running and no guessing about what the program will do. This is the same move a type checker
   or Rust's borrow checker makes: it checks a rule the code follows, rather than every behaviour the
   code could have.
3. **Each release point is allowed or it breaks.** It is allowed when it is inside the structure's own
   component, or listed under `except`, such as the mailer that must send the email. Anywhere else, it
   breaks.
4. **Passing a protected value straight to an effect breaks too,** for example `print(email)` or
   `logger.info(order)`, where `order` contains an email.
5. **While tests run,** archform remembers the text of every protected value it sees created. It looks
   for that text in everything written to the listed effects: console output, log records, files,
   network sends. A match is a break, with the place it was written. Nothing is stopped; the run is
   watched and reported.
6. **Where a type cannot be worked out,** for example an untyped argument, or a value passed through
   `Any`, the result is a question, never a pass.

So `data-flow` holds only when every release point is allowed, no protected value reaches an effect
directly, no test run wrote one out, and nothing was left unknown.

### 4.2 Custom check kinds

A custom check is a function registered in `archform.toml`:

```python
from archform.checks import Code, Scope, Violation

def no_module_state(code: Code, scope: Scope, params: Params) -> Iterable[Violation]:
    for unit in code.units(scope):
        for name in unit.top_level_assignments():
            if name.changeable:
                yield Violation(name.location, f"{name} is changeable module state")
```

It receives the code model (§5.1), the same read-only model archform's own checks use.

**Why a custom check stays deterministic:**
- It receives only the code model, never the file system.
- archform analyses the check's own code and refuses a check that has any effect from §3.
- Its findings are sorted before they are reported.
- It declares what it reads. If an adapter did not supply that, the result is a question.

### 4.3 Evidence

| Evidence kind | Is | Python |
|---|---|---|
| `unit-test` | an example test | a test with `@verifies(...)` |
| `property-test` | a test over generated inputs | a test with `@verifies(...)` that uses Hypothesis `@given` or `deal.cases` |
| `contract` | a precondition, postcondition or invariant checked when the code runs | a deal contract with `@verifies(...)` |
| `benchmark` | a timed test | a test with `@verifies(...)` that records its timing in the report |
| `mutation` | proof that the linked tests fail when the code is changed | a mutmut report |
| `test-report` | results from another tool | a report file named by a process variable |

Each adapter says how its language provides these (§5.2).

**Links:**
- `verifies("<fr>#<statement>")` points at an FR statement. In Python it's the decorator
  `@verifies(...)`; each adapter defines its own form.
- `verifies("<constraint>")` points at a constraint statement.
- A statement has evidence when at least one linked test counts as evidence (§4.5).

**Rules:**
- A statement with a time bound ("within 5 s") needs `benchmark` evidence.
- A `verification` process variable adds its evidence kind as a requirement for every statement it
  covers.

### 4.4 Free: built-in rules

Every project gets these without writing anything.

**Always on.** These are what make the record mean anything, so they cannot be turned off. Known
breaks can still be excepted.

| Rule | Holds when |
|---|---|
| record integrity | every file parses; every statement fits its grammar; every name resolves and is defined once; every FR's parent is defined; levels nest in order; every sentence archform renders also fits the EARS grammar; `archform fmt` changes nothing on a second run |
| coverage | everything the adapters find belongs to exactly one DP; FRs and DPs pair one-to-one |
| `encapsulation` | everything depends on a DP only through its interface |
| `container-boundaries` | code in one container does not import another container's components; they talk through endpoints, messages or data containers, or depend on a shared component |
| `data-ownership` | only a structure's own component changes it; others may hold it and pass it on |
| `no-cycles` | no cycle between siblings |
| traceability | every FR on the first level below the root, every constraint and every process variable serves an outcome |
| declared effects | every effect declaration in the code (`@deal.has`, `@deal.pure`) covers the effects archform finds |
| `permitted-effects` | when infrastructure is described, every resource effect the code has is granted |
| `representations-agree` | every structure's representations match |
| `messages-agree`, `endpoints-agree` | the two ends of every traced message and request use the same structures |
| `references-resolve` | every `refers-to` points at a recorded structure |
| evidence honesty | see §4.5 |

**What `encapsulation` means for components.** A component's public names are:
- the names its own module or package exports;
- plus those of its child modules that its language marks as public (§5.2).

Anything else inside it is private to it. So `cli` may use what `core` exposes, but not reach into
`mojo2verus.core.frontend` unless `core` makes it public. Nothing is written for this; the code
already says what is public. Tests are outside every DP and may reach in.

**On by default, tunable.** These are built-in constraints and process variables of the `maintain`
job, placed on the root:

| Name | Domain | Check | Default |
|---|---|---|---|
| `declared-libraries` | constraint | `declared-libraries` | the project's declared dependencies, plus vendored packages |
| `edge-types` | constraint | `edge-types` | `bool` returns allowed |
| `declared-errors` | constraint | `declared-errors` | |
| `access-sanity` | constraint | `access-sanity` | |
| `one-writer-per-data-store` | constraint | `one-writer-per-data-store` | |
| `least-privilege` | constraint | `least-privilege` | |
| `max-lines` | process | `max-lines` | function 200, class 1000 |
| `max-children` | process | `max-children` | 9 |
| `described-names` | process | `described-names` | |
| `min-depth` | process | `min-depth` | |
| `no-mode-parameters` | process | `no-mode-parameters` | |
| `narrow-parameters` | process | `narrow-parameters` | |
| `no-single-implementations` | process | `no-single-implementations` | |
| `co-change` | process | `co-change` | the last 500 commits |

**Tuning a built-in:** write an entry with the built-in's name, in the file of its domain. The entry
may set only:
- `with`, to change parameters;
- `except`, for known breaks;
- `on`, to narrow it to one subtree;
- `off: true`, which turns it off. A comment saying why is expected.

```yaml
# design/process.yaml
max-lines:
  with:
    function: 120
  except:
    - emit.Emitter  # 10,142 lines; splitting it is planned
```

**Free when the record asks for it.** Writing a constraint or process variable switches on testing
that goes with it, with nothing more to write (§4.5):
- a constraint with `effects: allow: []` turns on determinism by replay;
- a contract turns on generated cases.

### 4.5 Free: testing

`archform test` runs the project's own tests under observation, runs the tests archform generates, and
stores every result with a digest of the code it ran against. `archform check` then uses those results
for as long as the code they ran against is unchanged. The fast static checks run in `archform check`
on every edit. The observed ones come from the last `archform test`.

Two rules keep the results trustworthy:
- **Running code can only find breaks.** A run shows what did happen. It can turn a question into a
  break, but never a break into a pass, because a run cannot show that something never happens.
- **Everything archform generates runs with fixed seeds,** so the same code and tests give the same
  results.

**Watching the tests run.** Everything that happens is charged to the DP whose code did it:

| Observed | Checked against |
|---|---|
| effects: files, sockets, processes, the console, time, randomness, environment | `effects` constraints and declared effects |
| imports actually made | `may-depend-on`, `encapsulation`, `container-boundaries`, `no-cycles`, `declared-libraries` |
| calls that cross a component boundary | `encapsulation`, the design matrix |
| values crossing a component boundary | the annotations on the public signatures, and `edge-types`. A `NewType` is checked as its base type. |
| **changes to recorded structures**, charged to the component that made them | `data-ownership` |
| errors crossing a component boundary | `declared-errors` |
| protected values written to an effect | `data-flow` |
| contracts | the contracts |

**How data ownership is observed (Python):**
- **Attribute changes.** archform wraps `__setattr__` and `__delattr__` on recorded structures, so
  every change is charged to the component whose code made it.
- **Changes in place,** such as `order.items.append(...)`, which bypass `__setattr__`. When a structure
  is passed into another component, archform records a digest of its contents, and compares it when the
  call returns. A difference means that component changed it.
- **Code the tests never run** is analysed statically. A suspected change there is a question.

"Changes" relationships also feed the design matrix, so data coupling between siblings is caught by
`no-cycles` too.

Watching catches what static analysis cannot see: `eval`, dynamic imports, plugins, C extensions,
callbacks. Each adapter says how much it can observe (§5.2).

**Tests archform makes from what is there:**
- **Determinism by replay.** For code under a rule that allows no effects, archform records the calls
  made into it during the tests. It replays each call with a copy of the same arguments, in a
  different order. A different result breaks the rule. Arguments that cannot be copied make the result
  a question.
- **Cases from contracts.** Every function with a contract is run on generated inputs, filtered by its
  preconditions. In Python this is `deal.cases`.

archform does not fuzz functions that have no contract. There would be nothing to check the results
against.

**Evidence honesty.** A test counts as evidence for a statement only when:

| Condition | Otherwise |
|---|---|
| its link resolves | break |
| it passed in the latest run | break if it failed or errored. If it was skipped, or no run was read, the statement is to do. |
| it runs code in the statement's DP | break: it is linked to the wrong thing |
| it is the kind the statement needs | to do |
| it ran against the current code | to do: the evidence is out of date |

Tests with no link are listed, but they are not errors.

---

## 5. Adapters

An adapter reads one language or tool into the code model. The model and the record never mention a
language; only adapters do.

### 5.1 The code model

Every adapter supplies the parts it can, and declares the parts it cannot. A check that needs a part
nobody supplied gives a question.

| Part | What it holds |
|---|---|
| **units** | modules, packages, deployed resources, tables, each with its code name, location, size and the level it can map to |
| **public names** | each unit's interface, as its language or tool defines it |
| **dependencies** | imports, references between resources, foreign keys, each with its location |
| **symbols** | functions, types and fields, with signatures, sizes and locations |
| **structures** | types and tables, with their fields and the relationships between them |
| **calls and effects** | who calls what, and which effects start where |
| **permissions and connections** | for infrastructure: who is granted what, what can reach what, which settings point at which resource |
| **tests** | each test, its links, its evidence kind and its latest result |
| **observations** | what was seen while tests ran |

### 5.2 Languages and tools

They are supported in this order: Python, Terraform, SQL, TypeScript, Go, Rust.

| | Python | Terraform | SQL | TypeScript | Go | Rust |
|---|---|---|---|---|---|---|
| **Maps** | packages, modules, classes | resources | tables, views | packages, modules, classes | packages, types | crates, modules, structs and enums |
| **Code name** | `python:pkg.mod.Type` | `terraform:aws_s3_bucket.site` | `sql:orders` | `typescript:web/src/cart` | `go:shop/orders.Order` | `rust:crate::orders::Order` |
| **Public names** | the `_` convention | outputs, and what other resources reference | tables other components may read | `export` | capitalized names; `internal/` packages | `pub` |
| **Dependencies** | imports; `pyproject.toml` | references | foreign keys | imports; `package.json` | imports; `go.mod` | `use`; `Cargo.toml` |
| **Effects found from** | calls such as `open`, `socket`, `subprocess` | permissions and connections | statements that read or write | `fs`, `fetch`, `child_process`, `process.env` | `os`, `net`, `os/exec`, `time` | `std::fs`, `std::net`, `std::process`, `std::env` |
| **Link form** | `@verifies(...)` | | | `verifies(...)` in the test name or tag | a `verifies:` line in the test's comment | `#[verifies(...)]` |
| **Evidence tools** | pytest, Hypothesis, deal, pytest-benchmark, mutmut | | | vitest or jest, fast-check | go test, rapid, testing.B, go-mutesting | cargo test, proptest, Kani or contracts, criterion, cargo-mutants |
| **Watching tests** | strong: audit hooks, wrapped calls | none | none | partial | partial | weak |

Typed languages make some checks exact that are guesses in Python. Examples are `data-ownership` in
Rust, through private fields and `&mut`, and public names in Go and Rust. Python makes up for it at
runtime.

### 5.3 Infrastructure as code

The infrastructure description is the code for the container level.

**archform never contacts a cloud and never runs the infrastructure tool itself.** A `build` process
variable renders the plan (for Terraform, `terraform show -json` of a plan), and archform reads that
file. It also reads the source files, to give each finding its location. If the plan is older than its
inputs, findings that depend on it are to do.

**From resources to containers:**
- **Resources that run code or store data are containers.** Examples: `aws_ecs_service`,
  `aws_lambda_function`, `aws_db_instance`, `aws_s3_bucket`, `aws_sqs_queue`. Each is mapped to a DP in
  `physical.yaml`.
- **Supporting resources** (roles, policies, security groups) belong to the container that references
  them. A resource that several containers reference, such as a network, belongs to the system.
- **Coverage applies:** every resource in the plan belongs to exactly one DP.
- **The code deployed into a container** is written in its `physical.yaml` entry beside its resource,
  for example `[terraform:aws_ecs_service.api, python:shop.api]`. Where the plan names the code
  directly, as a Lambda's source folder does, the adapter follows it.

**Relationships between containers** come from three places in the plan:
- **permissions:** a role granted an action on a resource gives `read` or `write` of that container;
- **connections:** network rules that let one container reach another;
- **settings:** an environment variable set to another resource's address. `DATABASE_URL` set to the
  orders database's endpoint is an example.

**Linking code to resources.** A call in the code, such as a `boto3` write to a bucket, becomes the
resource effect `shop.receipts.write` when the bucket's name reaches the call through a setting the
plan sets. When archform cannot trace the name, the result is a question.

**What this gives for free:**
- `permitted-effects`: the code never needs access the infrastructure doesn't grant. Otherwise it would
  fail once deployed.
- `least-privilege`: access granted but never used.
- `one-writer-per-data-store`.
- `container-boundaries`.
- Effect constraints at the container level, for example "The storefront shall not write to the
  orders db."

After Terraform, other tools are read the same way, through their rendered output:
`docker compose config`, `helm template`, `cdk synth`, `pulumi preview --json`.

### 5.4 SQL

- **Tables are structures** of a data container. Their columns are fields, and foreign keys are
  relationships.
- **The schema is read from migrations.** The component whose code holds a table's migrations owns
  that table.
- **Reads and writes come from the code:** SQL statements and ORM models, attributed per table.
- `data-ownership` then applies to tables: only the owning component writes a table.

---

## 6. Grammars

Each grammar is checked with word lists (lexicons), not judgement. Every lexicon is built in and can
be extended or narrowed in `archform.toml`.

### 6.1 Job

```
job        = VERB object [context]
```

- `VERB` comes from the verb lexicon, in its base form.
- No solution words.
- No second verb joined by "and" or "or".

Example: `Verify that a Mojo program meets its spec`

### 6.2 Performer

```
performer  = noun phrase
```

- Not empty.
- No solution words.

Example: `Mojo developer`

### 6.3 Outcome

```
outcome    = "Minimize the " measure
measure    = "time it takes to " phrase
           | "time between " phrase " and " phrase
           | "likelihood that " clause
           | "number of " phrase
           | "amount of " phrase
           | "frequency of " phrase
```

- No solution words.
- No vague words.

Example: `Minimize the likelihood that a proof passes for a program that breaks its spec`

### 6.4 EARS statement (FRs and constraint statements)

```
statement  = [ "Where " feature ", " ]
             [ "While " state ", " ]
             [ "When " event ", " | "If " condition ", then " ]
             subject " shall " [ "not " ] response "."
feature    = "the " STRUCTURE [ possessive FIELD ] " is " ( "enabled" | "disabled" )
state      = "the " STRUCTURE [ possessive FIELD ] " is " VALUE
possessive = "'s " | "' "
subject    = "the " NAME
response   = VERB words
```

**States and features point at data.** Both name a field of a recorded structure, so a statement
cannot refer to a state or feature that does not exist:
- **`STRUCTURE`** is the last part of a recorded structure's name;
- **`FIELD`** is one of its fields. It may be left out when the structure has exactly one field that
  could hold the value: an enum for a state, a `bool` for a feature;
- **for a state, `VALUE`** is a member of that field's enum. Underscores read as spaces, and case is
  ignored;
- **a feature** is a `bool` field, and the clause says whether it is enabled or disabled.

All of these are exact checks. Examples:
- `While the order is paid, the receipts shall keep a receipt for the order.` Here `Order` has one enum
  field, `status`, and `paid` is one of its members.
- `Where the settings' dry run is enabled, the cli shall not write files.` Here `Settings` has a `bool`
  field `dry_run`.

The "When" and "If" clauses stay free text.

| Pattern | Has |
|---|---|
| ubiquitous | no Where, While, When or If |
| event | When |
| state | While |
| unwanted | If … then |
| optional | Where |
| complex | more than one of the above |

**Subject:** `NAME` is the last part of the FR's name, or of the constraint's `on` name. Underscores
read as spaces, and case is ignored. So in an FR named `mojo2verus.core.emit`, the subject is "the
emit".

**FR rule:** an FR has exactly one ubiquitous statement, and it has no "not". This is what makes "one
function per FR" checkable.

### 6.5 Quality checks on every EARS statement (INCOSE)

| Quality | Check |
|---|---|
| **Atomic** | exactly one "shall"; no "and" or "or" followed by a verb after "shall"; no "and/or" |
| **Measurable** | no vague words; a number after a bound word (within, under, over, at most, at least, less than, more than, up to) has a unit from the unit lexicon; a comparative (faster, more, fewer, …) has "than" after it |
| **Specific** | no pronouns (it, its, they, them, their, this, these, those); no escape clauses (if possible, as appropriate, where practical, as needed, if necessary); no open endings (etc., and so on, such as, including but not limited to); no modal other than "shall" (should, may, will, must, might, could, would) |
| **Active** | no "shall be" followed by a past participle |
| **Solution-free** | no solution words, for FRs on the first level below the root |
| **Readable** | one sentence; at most 40 words; no semicolons; no brackets |

**Exact or guess:**
- **Guesses**, which give a question when they fail: a verb after "and" or "or"; a comparative without
  "than"; a past participle after "shall be"; vague words and solution words, since a word can be a
  real term in the project's domain.
- **Exact**, which give a break when they fail: everything else.

Job and outcome statements are also checked for readability, with a limit of 30 words.

### 6.6 Lexicons

The built-in lexicons are: verbs, solution words, vague words, units, comparatives, pronouns, escape
clauses, open endings and modals. In `archform.toml`, each can be extended (`add`) or narrowed
(`remove`), for example when a vague word is a real term in the project's own domain.

---

## 7. The record

```
archform.toml           how archform runs here, and what it has been taught (adapters, effects, checks, lexicons)
design/
  customer.yaml         Customer domain
  functional.yaml       Functional domain
  physical.yaml         Physical domain
  process.yaml          Process domain
  log.jsonl             what happened: raised findings, answers, critiques, approvals
```

**Worked out, and never recorded:** levels, interfaces, effects, the design matrix, the process matrix,
sizes, observations, evidence results and check results. These are cached in `.archform/`, which git
ignores. Test reports and rendered plans are written there too.

### 7.1 Names

| Name | Form | Example |
|---|---|---|
| FR name (and its DP) | lowercase identifiers joined by dots, starting with the root | `mojo2verus.core.emit` |
| job, outcome, statement, constraint, process variable | lowercase words joined by hyphens | `wrong-proof-passes` |
| outcome reference | `job.outcome` | `verify-programs.wrong-proof-passes` |
| statement reference | `fr#statement` | `mojo2verus.core.emit#same-output` |
| code name | `adapter:name` (§5.2). Without a prefix, the default adapter. Names in a code adapter are read relative to the nearest DP that has code (§7.5). | `emit.translator_names`, `terraform:aws_s3_bucket.site` |
| library | an importable top-level package | `lark` |

**Why FR names are identifiers:** by default they name the code (§7.5).

**Resolving a name in an allow-list:** a name that starts with the root FR's name is an FR. Otherwise
it is a library. A name that is neither is an error.

**Each name is defined in exactly one place.** A domain file can become a folder of files, for example
`design/functional/mojo2verus.core.yaml`. A name defined twice is an error.

**Every FR's parent is defined.** `mojo2verus.core.emit` needs `mojo2verus.core`.

**Built-in names** (§4.4) are reserved. Writing one tunes the built-in; it does not define a new entry.

### 7.2 YAML rules

- Every value is read as text. Parameters are converted by their check kind's schema, so `no` stays
  "no".
- No anchors, aliases or tags. Duplicate keys are errors.
- **Comments are kept.** A comment beside an entry, or directly above it, is the reason for it.
  archform shows reasons in context and review. A reason is never required.
- `archform fmt` gives every file one canonical layout.

### 7.3 `design/customer.yaml`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `<job>` | job name | at least one | a job |
| `<job>.job` | job statement (§6.1) | yes | what is being done |
| `<job>.performer` | performer (§6.2) | yes | who does it |
| `<job>.outcomes.<outcome>` | outcome statement (§6.3) | at least one | how they judge it |

The name `maintain` is reserved. A project may give it `outcomes` only.

### 7.4 `design/functional.yaml`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `frs.<fr>` | FR name | the root, plus any others | an FR |
| `frs.<fr>.serves` | list of outcome references | on the first level below the root; not allowed elsewhere | the outcomes it serves. Deeper FRs serve through their parent, and the root's are worked out. |
| `frs.<fr>.statements.<name>` | EARS statement (§6.4) | at least one; exactly one ubiquitous | the function and its conditions |
| `constraints.<name>` | constraint name | | a constraint |
| `constraints.<name>.on` | one FR name | yes | where it applies: that FR and everything below it |
| `constraints.<name>.serves` | list of outcome references | yes | why it exists |
| `constraints.<name>.check` + `.with` | check kind + parameters | exactly one of `check` or `statement` | enforced by archform |
| `constraints.<name>.statement` | EARS statement | exactly one of `check` or `statement` | verified by evidence |
| `constraints.<name>.except` | list of code names | no; only with `check` | code the check skips; each entry must resolve to real code |

### 7.5 `design/physical.yaml`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `<fr>` | FR name | only where the default is wrong | what this DP is |
| value | list of code names (§7.1) | | the units it maps to: modules, packages, types, resources, tables |

**Rules:**
1. **Relative names.** In a code adapter, names are read inside the code of the nearest ancestor that
   has code of its own. The root's code is the project package. Infrastructure and SQL names are
   absolute.
2. **Default.** A DP with no entry maps to the module or package named after the last part of its
   name, inside that ancestor. Failing that, it maps to the type with the same name in CamelCase
   (`order` gives `Order`).
3. **A package covers what is inside it,** unless a lower DP claims part of it. The most specific claim
   wins. Units in a package that no child claims belong to the package's DP.
4. **A DP with no code of its own is a grouping.** Its code is its children's, and relative names pass
   through it.
5. **Level.** A DP's level is the level of what it maps to: a deployed resource makes a container; a
   module or package makes a component; a type or table makes a structure. A grouping takes its
   children's level.
6. **Representations.** A structure may list several units, at most one per adapter, for example
   `[python:Order, typescript:web/src/types.Order, sql:orders]`. They are representations of one
   structure, and `representations-agree` checks that they match.
7. **Coverage:**
   - everything the adapters find belongs to exactly one DP, vendored code aside;
   - something claimed by nobody is an error, and so is something claimed equally by two DPs;
   - a DP that maps to nothing and has no children is to do: "no code yet".

### 7.6 `design/process.yaml`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `<name>` | process variable name | | a process variable |
| `<name>.kind` | `code-rule`, `verification`, `validation`, `build` or `workflow` | yes | |
| `<name>.on` | one DP name | yes | where it applies: that DP and everything below it |
| `<name>.serves` | list of outcome references | yes | why it exists |
| **code-rule:** `check` + `with` | check kind + parameters | yes | the rule |
| **code-rule:** `except` | list of code names | no | code it skips |
| **verification:** `evidence` | evidence kind (§4.3) | yes | what each covered statement needs |
| **verification:** `report` | path pattern | for `test-report` | where results are |
| **validation:** `measures` | outcome reference | yes | the outcome it measures |
| **validation:** `report` | path | yes | where the measurement is |
| **build:** `step` | command | yes | what produces the files |
| **build:** `produces` | list of paths | yes | what it produces |
| **workflow:** `gate` | a gate from the list below | yes | |

| Gate | Holds when |
|---|---|
| `critique-before-review` | every changed design entry has a `critiqued` event for its current content before it is approved |
| `person-approves-design` | every changed design entry has an `approved` event from a person |
| `stop-on-error` | a change is not accepted while any check is broken |
| `countermeasure-on-escape` | a defect found by review or by a person, not by a check, is answered `fixed` only together with a countermeasure: the name of a new or changed constraint, statement or process variable that would catch it next time |

### 7.7 `design/log.jsonl`

The log is append-only, one event per line, ordered by time. Git merges it as a union
(`.gitattributes: design/log.jsonl merge=union`).

| Field | In | Meaning |
|---|---|---|
| `at` | every event | UTC timestamp |
| `by` | every event | who: a person or an agent |
| `event` | every event | `raised`, `answered`, `critiqued` or `approved` |
| `id` | `raised`, `answered` | worked out from `at`, `by`, `on` and `say`, so ids made on two branches cannot clash. Questions from guess checks (§4.1) are identified by their check, `on` and `digest` instead. |
| `on` | `raised`, `critiqued`, `approved` | the name it is about |
| `kind` | `raised` | `defect`, `question` or `idea` |
| `say` | `raised`, `answered` | the text |
| `evidence` | `raised` | the exact words or code it is about |
| `answer` | `answered` | `fixed`, `accepted`, `declined` or `answered` |
| `countermeasure` | `answered` | a name, when the gate requires one |
| `digest` | `critiqued`, `approved`, and `answered` for a question | a digest of the content the event is about. When that content changes, the question is asked again. |

Check results are not logged. They are worked out each time. Only what people and agents raise,
answer, critique and approve is logged.

### 7.8 `archform.toml`

| Section | Keys | Meaning |
|---|---|---|
| `[settings]` | `tests`, `test_command`, `test_reports`, `vendor`, `editor` | where tests are and how to run them |
| `[adapters]` | `default` | the adapter for code names without a prefix |
| `[adapters.<name>]` | that adapter's settings, for example `source` for a language, or `plan` and `source` for Terraform | where each adapter reads from |
| `[lexicon.<name>]` | `add`, `remove` | adjust a built-in lexicon |
| `[effects."<name>"]` | `description`, `calls` | a custom effect: the calls that perform it |
| `[checks.<name>]` | `description`, `code` (`path.py:function`), `params` (name → type and default), `reads`, `exact` (true or false) | a custom check kind |

### 7.9 Starting from existing code

`archform init` records what is there, so the first check holds. After that, anything new breaks:
- **FRs and DPs:** one per deployed resource, package or module, with statements left to do.
- **Effects:** one `effects` constraint per top-level DP, allowing what it does today.
- **Dependencies:** `may-depend-on` per top-level DP, allowing what it depends on today.
- **Known breaks of built-in rules** (an oversized class, a reach into another component, an
  undeclared library, a shared database) go under that rule's `except`.

Every `except` entry is visible debt. Improving the design then means removing entries and narrowing
allow-lists, one reviewable change at a time.

---

## 8. Worked examples

### 8.1 mojo2verus: one container, Python only

Some entries show what could be added, and don't exist in mojo2verus today: the build step, the
`verus.run` effect and the custom check.

`design/customer.yaml`:

```yaml
verify-programs:
  job: Verify that a Mojo program meets its spec
  performer: Mojo developer
  outcomes:
    wrong-proof-passes: Minimize the likelihood that a proof passes for a program that breaks its spec
    slow-verdict: Minimize the time between changing a program and seeing whether its proof passes
    verus-to-write: Minimize the amount of Verus a developer must write to state a spec
```

`design/functional.yaml`:

```yaml
frs:
  mojo2verus:
    statements:
      translate: The mojo2verus shall translate a Mojo program with specs into a Verus program with the same meaning.

  mojo2verus.core:
    serves: [verify-programs.wrong-proof-passes, verify-programs.verus-to-write]
    statements:
      translate: The core shall translate Mojo source text into Verus source text.

  mojo2verus.core.frontend:
    statements:
      read: The frontend shall read Mojo source text into a syntax tree with source positions.

  mojo2verus.core.semantics:
    statements:
      type: The semantics shall give each expression in a syntax tree a Mojo type.

  mojo2verus.core.models:
    statements:
      provide: The models shall provide a Verus model for each supported standard-library type.

  mojo2verus.core.emit:
    statements:
      translate:   The emit shall translate a checked program into Verus.
      same-output: When given the same program twice, the emit shall produce the same Verus.
      unmodelled:  If a construct has no model, then the emit shall stop with an error that names the Mojo line.

  mojo2verus.core.erase:
    statements:
      remove:         The erase shall remove specs from Mojo source text.
      same-positions: When given Mojo source text, the erase shall keep every remaining character at the same line and column.

  mojo2verus.cli:
    serves: [verify-programs.slow-verdict]
    statements:
      run: The cli shall translate the files named on the command line.

constraints:
  machine-effects:
    on: mojo2verus
    serves: [verify-programs.wrong-proof-passes]
    check: effects
    with:
      allow: [read, write, stdout, stderr, syscall]

  pure-core:  # a proof must not depend on the machine it was made on
    on: mojo2verus.core
    serves: [verify-programs.wrong-proof-passes]
    check: effects
    with:
      allow: []
    except:
      - emit.translator_names  # Reads its own source to list names. A build step would remove this.
      - stdlib_names

  emit-without-parser:
    on: mojo2verus.core.emit
    serves: [maintain.unrelated-breakage]
    check: may-depend-on
    with:
      allow: [mojo2verus.core.semantics, mojo2verus.core.models]

  fast-verdict:
    on: mojo2verus
    serves: [verify-programs.slow-verdict]
    statement: When given a 10,000-line program, the mojo2verus shall finish translating within 5 s.
```

`design/physical.yaml`. Only the DPs whose code is not where their name points. The default adapter is
Python, so no prefixes are needed:

```yaml
mojo2verus.core.frontend: [parse, ast, build]
mojo2verus.core.semantics: [types, stdlib_model, stdlib_names]
mojo2verus.core.models: [prelude, collections_rs, spans_rs, strings_rs, simd_rs]
mojo2verus.cli: [__main__]
```

- No deployment is described, so the system is the one implicit container.
- `core` is a grouping, so its children are looked up in `mojo2verus`.
- `emit` and `erase` are found by default, at `mojo2verus/emit.py` and `mojo2verus/erase.py`.

`design/process.yaml`. The first entry tunes a built-in (§4.4). The rest are the project's own:

```yaml
max-lines:
  except:
    - emit.Emitter  # 10,142 lines; splitting it is planned

property-tests:
  kind: verification
  on: mojo2verus.core
  serves: [maintain.unrelated-breakage]
  evidence: property-test

benchmarks:
  kind: verification
  on: mojo2verus
  serves: [verify-programs.slow-verdict]
  evidence: benchmark

soundness-oracle:
  kind: validation
  on: mojo2verus
  serves: [verify-programs.wrong-proof-passes]
  measures: verify-programs.wrong-proof-passes
  report: .archform/oracle.xml

generated-names:
  kind: build
  on: mojo2verus.core.emit
  serves: [maintain.unrelated-breakage]
  step: python scripts/gen_names.py
  produces: [src/mojo2verus/translator_names.py]

critique-first:
  kind: workflow
  on: mojo2verus
  serves: [maintain.unrelated-breakage]
  gate: critique-before-review

stop-on-error:
  kind: workflow
  on: mojo2verus
  serves: [maintain.unrelated-breakage]
  gate: stop-on-error
```

`archform.toml`:

```toml
[settings]
tests        = ["tests"]
test_command = "pytest"
vendor       = ["src/mojo2verus/_vendor"]

[adapters]
default = "python"

[adapters.python]
source = ["src"]

[effects."verus.run"]
description = "Starts the Verus verifier"
calls       = ["mojo2verus.verus.run_verus"]

[checks.no-module-state]
description = "Modules keep no changeable state at the top level"
code        = "tools/archform_checks.py:no_module_state"
reads       = ["symbols"]
```

What archform renders, for example with `archform show mojo2verus.core`:

```
mojo2verus.core: The core shall translate Mojo source text into Verus source text.
  serves: verify-programs.wrong-proof-passes, verify-programs.verus-to-write
  constraints in force:
    The core shall have no side effects, except in emit.translator_names and stdlib_names.
    The mojo2verus shall import only the standard library and its declared or vendored packages.
  process in force: max-lines, max-children, described-names, min-depth,
    no-mode-parameters, narrow-parameters, no-single-implementations, co-change,
    property-tests, critique-first, stop-on-error

                frontend  semantics  models  emit  erase
  frontend         X
  semantics        X         X
  models                              X
  emit             X         X        X       X
  erase            X                                X

  broken: emit depends on frontend (emit.py:2377); emit-without-parser allows only semantics, models
```

### 8.2 shop: four containers, four adapters

An illustration of containers, infrastructure, SQL and structures. It is not a real project.

`design/customer.yaml`:

```yaml
buy-products:
  job: Buy a product online
  performer: Shopper
  outcomes:
    lost-order: Minimize the likelihood that a placed order is lost
    checkout-time: Minimize the time it takes to complete a checkout
```

`design/functional.yaml`:

```yaml
frs:
  shop:
    statements:
      sell: The shop shall take orders for products from shoppers.

  shop.storefront:
    serves: [buy-products.checkout-time]
    statements:
      order: The storefront shall let a shopper place an order for a product.

  shop.api:
    serves: [buy-products.lost-order]
    statements:
      record: The api shall record each placed order.

  shop.api.orders:
    statements:
      store: The orders shall turn a placed order into a stored order.

  shop.api.orders.order:
    statements:
      lines: The order shall give every line a product and a quantity.

  shop.orders_db:
    serves: [buy-products.lost-order]
    statements:
      keep: The orders db shall keep every stored order.

  shop.receipts:
    serves: [buy-products.lost-order]
    statements:
      keep: The receipts shall keep a receipt for each stored order.

constraints:
  storefront-through-api:
    on: shop.storefront
    serves: [buy-products.lost-order]
    check: effects
    with:
      allow: [network]
```

`design/physical.yaml`:

```yaml
shop.storefront: [terraform:aws_s3_bucket.site, typescript:web/src]
shop.api:        [terraform:aws_ecs_service.api, python:shop.api]
shop.orders_db:  [terraform:aws_db_instance.orders, sql:orders, sql:order_lines]
shop.receipts:   [terraform:aws_s3_bucket.receipts]
```

- `shop.api.orders` is found by default, at `shop/api/orders`.
- `shop.api.orders.order` is found by default as the type `Order` inside it, so it is a structure.

`design/process.yaml`:

```yaml
terraform-plan:
  kind: build
  on: shop
  serves: [maintain.unrelated-breakage]
  step: terraform -chdir=infra plan -out=../.archform/plan && terraform -chdir=infra show -json ../.archform/plan > .archform/plan.json
  produces: [.archform/plan.json]
```

`archform.toml`:

```toml
[settings]
tests        = ["tests"]
test_command = "pytest"

[adapters]
default = "python"

[adapters.python]
source = ["src"]

[adapters.terraform]
source = "infra"
plan   = ".archform/plan.json"

[adapters.sql]
migrations = "migrations"

[adapters.typescript]
source = ["web"]
```

What archform renders with `archform show shop`, at the container level:

```
shop: The shop shall take orders for products from shoppers.
  context: Shopper → storefront

                storefront  api  orders_db  receipts
  storefront        X        X
  api                        X       X          X
  orders_db                          X
  receipts                                      X

  broken: api writes receipts (receipts.py:31), but the api's role is not granted s3:PutObject on aws_s3_bucket.receipts
  question: least-privilege: the api's role may delete from orders_db, and no code does
```

- `storefront-through-api` allows `network` only. Writing to the orders database would be
  `shop.orders_db.write`, which it does not allow.
- `one-writer-per-data-store` holds: only the api writes `orders_db` and `receipts`.
- The SQL migrations for `orders` live in `shop.api.orders`, so only that component may write the
  table.

---

## 9. Commands and views

Views are generated from the record and the code. None of them is written by hand.

| Command | Does |
|---|---|
| `archform init` | records what is there (§7.9) |
| `archform check` | runs every static check, and uses the latest observed results that are still current. Fast enough to run after every edit. |
| `archform test` | runs the project's tests under observation, then archform's generated tests, then everything `check` does (§4.5) |
| `archform fmt` | gives every design file its canonical layout |
| `archform rename <old> <new>` | renames an FR and its DP everywhere it is used: the record, and every `verifies` link in the tests |
| `archform show [name]` | one level of the zigzag: the FR's statements, its children, the design matrix, the constraints and process variables in force (as sentences), evidence, and what is broken |
| `archform show --data [name]` | the data model: each structure, what it contains and refers to, with cardinalities; and a create, read, update and delete table of structures against the DPs that access them |
| `archform context <file or name>` | what an agent needs before changing that code: the chain up to its outcomes and job, its statements, the constraints and process variables in force, the interfaces of what it depends on, and evidence |
| `archform review <base>` | what a change does to the record, in domain order (customer, functional, physical, process), then what broke |
| `archform next` | what is to do, in the order the design matrix allows building it |
| `archform findings` | open threads and unanswered questions from the log, newest first |
| `archform checks` / `archform effects` | the registered check kinds and effects, with their parameters and meanings |

C4's views are cuts of the physical domain: context, containers, components and code are its levels.

---

## 10. Skills

The methods for arriving at a good record are shipped as agent skills. Each skill produces one part of
the record, and is finished when that part's checks hold. A skill is offered when what it produces is
missing, or when a check result calls for it.

| Skill | Produces | Offered when | Finished when |
|---|---|---|---|
| `interview-for-jobs` | jobs, performers and outcomes, from a jobs-to-be-done interview with a person | the customer domain is empty, or a request arrives phrased as a solution | the job and outcome grammars hold, and the person has confirmed each outcome |
| `write-frs` | FRs and their statements, from the outcomes | an outcome is served by no FR | the EARS and quality checks hold, and every first-level FR serves an outcome |
| `decompose` | the next level of the zigzag: a DP for an FR, then the FRs it gives rise to | an FR has no DP, or `max-children` breaks | FRs and DPs pair one-to-one, and `no-cycles` and `max-children` hold |
| `design-data` | the structures and named types that cross edges, written as code first | `edge-types` breaks, or an FR's DP is a structure with no type yet | `edge-types`, `representations-agree` and `references-resolve` hold |
| `resolve-coupling` | a change that removes a cycle, using TRIZ separation and the ASIT closed world | `no-cycles` breaks, or `co-change` asks | `no-cycles` holds |
| `set-limits` | constraints, and tuning of built-ins | an FR has statements but nothing limits its DP, or a built-in needs tuning | every constraint serves an outcome and is enforced |
| `choose-process` | process variables: verification, validation, build steps, gates | statements need evidence that no process variable provides | every statement has the evidence its form and the process in force require |
| `adopt` | the record for existing code, through `archform init`, then paying down `except` entries | a project has code but no record | the first check holds, and each later run removes debt |
| `critique` | `critiqued` log events, from a critic that has seen none of the work | an entry changed since it was last critiqued | every changed entry has a critique for its current content |
| `review` | `approved` log events, or findings, for a change, read in domain order | a change is ready for review | every changed entry is approved or has an open finding |

---

## 11. Where each framework lands

| Framework | Lands as |
|---|---|
| Jobs to be done / outcome-driven innovation (Ulwick) | the customer domain: the job and outcome grammars, and validation |
| Axiomatic design (Suh) | the four domains, both matrices, the zigzag, the independence axiom (`no-cycles`), the information axiom (judgement) |
| Object-oriented axiomatic design (Do and Suh) | structures as the lowest DPs, with operations as the matrix entries that relate them to FRs |
| EARS and INCOSE | the statement grammar and its quality checks |
| Parnas and Ousterhout | `encapsulation` and `data-ownership`, always on; worked-out interface size and depth; the `min-depth`, `no-mode-parameters`, `narrow-parameters`, `edge-types` and `described-names` checks |
| C4 | the four levels of the physical domain, and its views |
| Baldwin and Clark (design rules) | structures and named types that other components build against, and `edge-types` |
| Design by contract (deal) and property tests | the effect vocabulary, contracts and property tests as evidence, generated cases |
| TRIZ and ASIT | the method for when the design matrix has a cycle. Not stored. |
| Jidoka | the `stop-on-error` and `countermeasure-on-escape` gates, and the log |

---

## 12. Open questions

1. **Build steps:** how archform decides that build outputs are current without running the step
   itself, for example by recording a digest of the inputs in the output.
2. **Validation reports:** the format a measurement report uses to give the outcome's value.
3. **Who is a person:** how `person-approves-design` tells a person from an agent in `by`.
4. **Adapters after Python:** the exact link forms and effect lists for TypeScript, Go and Rust, and
   how much each can observe while tests run.
5. **Infrastructure:** which resource types count as containers in each provider, and how far setting
   values can be traced from the plan to a call in the code.
6. **Defaults on existing systems:** whether `one-writer-per-data-store`, `edge-types` and
   `declared-errors` should start on (with everything current under `except`) or start off.
7. **The maintainer job's outcomes:** whether the built-in set is right and complete.
8. **Performers and containers:** relationships are never written, so how a performer is tied to the
   containers they use must be worked out. One job is easy. With several jobs, archform can see which
   containers are reachable from outside, but not which performer reaches which.
9. **The critique rubric:** the questions a critic asks of each term (job, outcome, FR, DP), and how
   they are versioned.
10. **Pinning the rule set:** how `archform.toml` names the rule-set version, so that a new archform
    release never changes results until the project upgrades.
11. **Compatible changes:** a check that structures crossing containers, or stored, change only in
    compatible ways compared with the base, unless a migration is recorded.
12. **The name:** `archform` for the tool and the record.
