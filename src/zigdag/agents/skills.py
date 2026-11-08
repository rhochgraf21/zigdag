"""The skills (DESIGN2 §10): how to arrive at a good record, as text any agent can follow. Each skill says when it
is offered, what it produces, its steps, and the checks that say it is finished.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str  # when to use it: what an agent reads to decide
    body: str


CORE = Skill("zigdag", "Work in a project whose design is kept by zigdag (design/*.yaml and zigdag.toml). Use before "
             "changing code or design, when planning a change, or when unsure what to do next.", """
# Working with zigdag

The design in `design/` says who the system is for (customer.yaml), what it must do (functional.yaml),
what code does it (physical.yaml), and how it is made (process.yaml). zigdag checks the code against it.

1. **Orient:** `zigdag show` for the root, `zigdag show <fr>` for one level, `zigdag next` for what is to do.
2. **Before changing code:** `zigdag context <file>`. It says why the code exists, what it must do, the limits
   in force, and the exact signatures of what it uses. Stay within them.
3. **Change the design by editing design/*.yaml**, then `zigdag fmt` and `zigdag check`. Rename an FR only with
   `zigdag rename <old> <new>`: it updates every use, the tests' links, and keeps the code it points at.
4. **Link tests to what they verify:** `@verifies("fr#statement")` from `zigdag`. Run them with `zigdag test`:
   it watches what the code does while they run, and their results count only for the code as it was then.
5. **After every change:** `zigdag check`. A break is an error: fix it, or change the design on purpose. A question
   is answered once, with a reason: `zigdag answer <digest> accepted|declined|answered "<why>" --by <you>`.
6. **Raise what you notice,** in your work or anyone's: `zigdag raise defect|question|idea <name> "<what>" --by
   <you> --evidence "<exact words or code>"`. Do not fix what is outside your task.
7. **Before asking for review:** `zigdag review main`, and read it as a reviewer would. Changed entries need a
   critique from a fresh critic (the critique skill) before review. You never approve your own work.
""")

INTERVIEW_FOR_JOBS = Skill("interview-for-jobs", "Find who the system is for and what they are trying to get done. "
                           "Use when design/customer.yaml has no jobs, or a request arrives phrased as a solution.", """
# Interview for jobs (jobs to be done, outcome-driven innovation)

**Produces:** jobs, performers and outcomes in design/customer.yaml, from an interview with a person.

1. Ask who uses the result, who pays, who operates it, who is harmed when it fails. Each is a possible performer.
2. For each performer, ask what they are trying to get done, with no product in it. Write the job as a verb and
   its object: "Verify that a Mojo program meets its spec".
3. Ask how they judge whether the job went well. Each answer is an outcome:
   "Minimize the time it takes to ...", "Minimize the likelihood that ...", "Minimize the number of ...".
4. Ask "why?" of every solution in the request until the answer stops being a solution.
5. Read each outcome back to the person in their words. Keep only the ones they recognise.

**Finished when:** `zigdag check` passes the job and outcome grammars, and the person confirmed each outcome.
""")

WRITE_FRS = Skill("write-frs", "Write functional requirements as EARS statements. Use when an outcome is served by no "
                  "FR, or zigdag check flags a statement.", """
# Write FRs

**Produces:** FRs in design/functional.yaml, each with one ubiquitous statement (its function) and any
conditioned statements that pin it down.

1. For each outcome no FR serves, name the function that would move it: "The <name> shall <verb> <object>."
2. One function per FR. Two verbs joined by "and" are two FRs.
3. Add conditions only to pin the function down: "When <trigger>, ...", "If <condition>, then ...",
   "While the <structure> is <state>, ...". A condition that adds a new function is a new FR.
4. Replace vague words with numbers and units. No pronouns, no "should", no "etc.".
5. First-level FRs say which outcomes they serve.

**Finished when:** `zigdag check` reports no EARS or quality problem, and every first-level FR serves an outcome.
""")

DECOMPOSE = Skill("decompose", "Take one zigzag step: choose the design parameter for an FR, then the FRs it gives rise "
                  "to. Use when an FR has no code yet, or max-children breaks.", """
# Decompose (zigzag)

**Produces:** the next level of the tree: child FRs under an FR, each to be performed by a child DP.

1. Read `zigdag context <fr>`.
2. Name at least two ways to perform the FR. Prefer the one with the fewest assumptions and the most chance of
   meeting the statements, and the one that reuses what exists.
3. From the chosen way, derive the parts it needs. Split by what is likely to change, not by steps. Three to nine.
4. Write each part as a child FR with its function. Name it after the code that will perform it.
5. Look at `zigdag show <fr>`: the design matrix should have no cycle.

**Finished when:** FRs and DPs pair one to one, and `no-cycles` and `max-children` hold.
""")

DESIGN_DATA = Skill("design-data", "Design the data that crosses between components. Use when edge-types, "
                    "data-ownership or references-resolve breaks, or an FR is performed by a structure that has no "
                    "type yet.", """
# Design data

**Produces:** structures (types recorded as DPs) and named types for everything that crosses an edge.

1. List what each component passes to others: parameters, returns, fields. `zigdag show --data <fr>` shows the
   structures there, what each contains and refers to, and which code creates, reads and changes each.
2. For each plain value (str, int, Path), give it a name with a meaning: `OrderId = NewType("OrderId", str)`.
3. For each class that crosses, record it as a structure: an FR whose subject is the class, performed by the type.
   Mark its identity with a field named `id`; another structure refers to it by that field's type.
4. Keep changes with the owner: a structure is changed only by the component that defines it. Give that
   component the operation (`order.pay()`) instead of setting fields from outside.
5. Give personal data its own named type (`Email = NewType("Email", str)`), and protect it with a `data-flow`
   constraint naming the effects it must never reach.
6. Write the structure's invariants as statements, and verify them with property tests or contracts.

**Finished when:** `edge-types`, `data-ownership`, `references-resolve` and `representations-agree` hold for the
component.
""")

RESOLVE_COUPLING = Skill("resolve-coupling", "Remove a cycle between siblings. Use when no-cycles breaks.", """
# Resolve coupling (TRIZ separation, ASIT closed world)

**Produces:** a change that removes the cycle, with its reason in a comment.

1. `zigdag show <parent>`: find the cycle in the design matrix, and the line of code behind each edge.
2. State it as a contradiction: "making A depend on B lets A ..., but B needs ... from A".
3. Try separation, in order: move the shared part into a new sibling both can use, or up into the parent; let the
   lower part define what the upper one implements; pass data instead of a reference; split the behaviour that
   needs the other side into its own part.
4. Prefer what already exists: remove a dependency before adding an abstraction.

**Finished when:** `no-cycles` holds.
""")

SET_LIMITS = Skill("set-limits", "Write constraints and tune built-in rules. Use when an FR has statements but nothing "
                   "limits how it may be built, or a built-in rule needs tuning.", """
# Set limits

**Produces:** constraints in design/functional.yaml, and tunings of built-in rules.

1. Ask what must never happen at this part's edge: which effects, which dependencies.
2. Write each limit as a constraint on the highest FR whose whole subtree must keep it, with the outcome it serves.
3. Prefer allow-lists: `effects: allow: []` for pure code, `may-depend-on: allow: [...]` for boundaries.
4. A known break goes under `except`, with a comment saying why. It is debt.

**Finished when:** every constraint serves an outcome, and `zigdag check` reports it holding or its debt.
""")

CHOOSE_PROCESS = Skill("choose-process", "Choose how the code is made and checked. Use when statements need evidence no "
                       "process variable provides.", """
# Choose process

**Produces:** process variables in design/process.yaml: verification, validation, build steps and gates.

1. For pure parts, require property tests: `kind: verification, evidence: property-test`.
2. For statements with time bounds, require benchmarks.
3. For outcomes you can measure, add a validation that reads the measurement.
4. For the team's workflow, add gates: `critique-before-review`, `person-approves-design`, `stop-on-error`,
   `countermeasure-on-escape`.

**Finished when:** every statement has the evidence its form and the process in force require.
""")

ADOPT = Skill("adopt", "Bring an existing codebase under zigdag. Use when a project has code but no design/.", """
# Adopt

**Produces:** a record of the code as it is, then a steady paying down of debt.

1. `zigdag init`. It writes an FR for each package and module, the effects and dependencies of each top-level
   part as they are today, and every known break under `except`.
2. Write the jobs (interview-for-jobs), then each FR's function (`zigdag next` lists them in build order).
3. Each later change removes `except` entries or narrows an allow-list. Never add new debt silently.

**Finished when:** the first `zigdag check` has no breaks, and each later run has less debt.
""")

CRITIQUE = Skill("critique", "Have changed design entries critiqued by a fresh critic. Use before review, when the "
                 "critique-before-review gate asks.", """
# Critique

**Produces:** `critiqued` events in design/log.jsonl, and findings raised for what the critic noticed.

1. `zigdag critique --request --base main`. It writes .zigdag/critique/request.json: the changed entries, what
   they serve, and the rubric questions still to ask.
2. Give that file, and nothing else, to a fresh agent that has not seen the work. It answers in the JSON form the
   request describes, quoting the entry's exact words as evidence.
3. `zigdag critique --record <answer.json> --by <critic>`.
4. Answer each raised finding: fix it, or decline it with a reason.

**Finished when:** every changed entry has a critique for its current content.
""")

REVIEW = Skill("review", "Review a change to the design. Use when a change is ready, or before approving.", """
# Review

**Produces:** `approved` events, or findings, for a change.

1. `zigdag review <base>`: read it in order: customer, functional, physical, process, then what the change brought.
2. For each changed entry, ask whether it still serves its outcomes and whether the rule sentences say what was meant.
3. Raise what is wrong: `zigdag raise defect <name> "<what>" --by <you>`.
4. A person approves: `zigdag approve --base <base> --by <person>`. An agent never approves its own work.

**Finished when:** every changed entry is approved by a person or has an open finding.
""")

SKILLS: Mapping[str, Skill] = {s.name: s for s in (CORE, INTERVIEW_FOR_JOBS, WRITE_FRS, DECOMPOSE, DESIGN_DATA,
                                                   RESOLVE_COUPLING, SET_LIMITS, CHOOSE_PROCESS, ADOPT, CRITIQUE,
                                                   REVIEW)}
