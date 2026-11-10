# The rules

Every rule zigdag can hold a project to. This file is what `zigdag checks` prints, made from the same list the checks run from.

## Always on

These cannot be switched off. A known break can be listed under the rule's `except`.

| Rule | What it holds the code to | Settings | When it fails, it is |
|---|---|---|---|
| `container-boundaries` | The project shall not import code from another container. | none | a break |
| `data-ownership` | The project shall change each structure only from the component that owns the structure. | none | a break, or a question |
| `encapsulation` | The project shall reach each other design parameter only through the public names of that design parameter. | none | a break |
| `endpoints-agree` | The project shall use the structures of an endpoint when calling the endpoint. | none | a break, or a question |
| `messages-agree` | The project shall use one structure for every message on a queue. | none | a break, or a question |
| `no-cycles` | The project shall keep the dependencies between sibling design parameters free of cycles. | none | a break |
| `references-resolve` | The project shall refer only to recorded structures. | none | a break |
| `representations-agree` | The project shall keep every representation of a structure in agreement. | none | a break |

These are checked always too, and have nothing to set:

- Every design file can be read, every sentence fits its grammar, and every name is defined once.
- Every module belongs to exactly one part of the design.
- Every requirement on the first level, and every rule, serves a goal someone has.
- A function that declares its effects has no others, and every contract holds on generated inputs.
- A test counts for a requirement only if it passed, ran that part's code, and ran against the code as it is.

## On by default

These are on without being written. To change one, write an entry with its name in the design file of its kind, with `with` for its settings, `except` for known breaks, `on` to narrow it, or `off: true`. `zigdag init --default` writes them all out.

| Rule | What it holds the code to | Settings | When it fails, it is |
|---|---|---|---|
| `access-sanity` | The project shall read each stored structure that a design parameter creates. | none | a question |
| `contracted-interfaces` | The project shall give a contract to each function declared without effects that an interface offers. | none | a break |
| `declared-errors` | The project shall raise only declared errors of project-defined types between components. | none | a break, or a question |
| `declared-libraries` | The project shall import only the standard library and declared or vendored packages. | none | a break |
| `described-names` | The project shall describe each public name in one line. | none | a break, or a question |
| `designed-modules` | The project shall hold only the modules that the design names. | none | a break |
| `edge-types` | The project shall pass only project-defined types between components. | `bool-parameters` = allowed, `bool-returns` = allowed, `bool-fields` = allowed | a break |
| `max-children` | The project shall have at most 9 children under each functional requirement. | `count` = 9 | a break |
| `max-lines` | The project shall keep each function within 200 lines, each class within 1000 lines and each file within 1000 lines. | `function` = 200, `class` = 1000, `file` = 1000 | a break |
| `mutation` | The project shall have the contract of each function declared without effects notice every small change to the function. | `paths` = 200, `seconds` = 10 | a break, or a question |
| `narrow-parameters` | The project shall take only the data that each function uses. | none | a question |
| `no-single-implementations` | The project shall not keep an abstraction with only one implementation. | none | a question |
| `one-writer-per-data-store` | The project shall give each data container exactly one writing container. | none | a break |
| `planned-effects` | The project shall make every decision in a function that is declared without effects. | none | a break, or a question |

## On when you write a rule for them

Each of these is used by writing a rule that names it under `check`, and the part of the design it is `on`.

| Rule | What it holds the code to | Settings | When it fails, it is |
|---|---|---|---|
| `data-flow` | For example: The project shall not use Email values when writing to standard output. | `data` (must be given), `never-reaches` (must be given) | a break, or a question |
| `effects` | For example: The project shall have no side effects other than reading files. | `allow` (must be given) | a break |
| `lint` | The project shall break no rule of the linter of the project. | none | a break |
| `may-depend-on` | For example: The project shall depend only on core. | `allow` (must be given) | a break |
| `security` | The project shall break no rule of the security checker of the project. | none | a break |
| `types` | The project shall break no rule of the type checker of the project. | none | a break |

## Designed, and not built yet

Nothing checks these in this version: no adapter reads infrastructure or git history yet. A rule that names one is asked about, never passed.

| Rule | What it holds the code to | Settings | When it fails, it is |
|---|---|---|---|
| `co-change` | The project shall not change sibling design parameters together without a dependency between the siblings. | `commits` = 500, `threshold` = 0.5 | a question |
| `least-privilege` | The project shall request only the access that the code uses. | none | a question |
| `permitted-effects` | The project shall use only the access that the infrastructure grants. | none | a break |

## Gates on a change

A gate is on when a `workflow` rule names it. `zigdag check --base <revision>` and `zigdag ready --base <revision>` hold a change to them.

| Gate | Holds when |
|---|---|
| `critique-before-review` | Every changed design entry is critiqued, at its current content, before it is approved. |
| `person-approves-design` | Every changed design entry is approved by a person. |
| `stop-on-error` | A change is not accepted while any check breaks. |
| `countermeasure-on-escape` | A defect that a person found, and no check did, is closed only together with the rule or requirement that will catch it next time. |
