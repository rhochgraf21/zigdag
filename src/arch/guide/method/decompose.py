"""Zigzag decomposition: choose a design parameter, then derive the requirements of its parts."""

from __future__ import annotations

from arch.guide.method.model import AbstractOp, Method, MethodName, Step, WorkedExample
from arch.model.ids import DesignPath, Text

DECOMPOSE = Method(
    name=MethodName.DECOMPOSE,
    title=Text("Decompose a component (zigzag)"),
    when=Text("A component is too large for one person or agent to hold in mind, or its requirement needs "
              "several distinct mechanisms."),
    inputs=(Text("The component and its requirement, criteria and constraints in force"),),
    steps=(
        Step(Text("Read the component's context first."), (AbstractOp.CONTEXT,)),
        Step(Text("Name at least two candidate solutions for its requirement. Prefer the one with the fewest "
                  "assumptions and the highest chance of meeting the criteria (the information axiom), and the one "
                  "that reuses what already exists (ASIT closed world).")),
        Step(Text("Record the choice: what was chosen, over what, because of what."), (AbstractOp.ADD_DECISION,)),
        Step(Text("Derive the parts the chosen solution needs. Split by secrets, not by steps: each child hides one "
                  "decision that is likely to change (Parnas). Aim for three to nine children.")),
        Step(Text("Add each child with its requirement, solution and secret."), (AbstractOp.ADD_COMPONENT,)),
        Step(Text("Declare which siblings each child uses; export only the children others must reach."),
             (AbstractOp.LINK,)),
        Step(Text("Look at the matrix. Uncoupled is ideal; decoupled gives an order; coupled means a cycle to resolve "
                  "before going further."), (AbstractOp.MATRIX, AbstractOp.PLAN)),
        Step(Text("Stop when a child can be built and tested by one agent in one focused session, its context fits "
                  "on a screen, and it has one secret.")),
    ),
    exit_criteria=(
        Text("Every child states realizes, solution and hides, and has at least one criterion"),
        Text("The matrix is not coupled, or the coupling is accepted with a decision"),
        Text("Between three and nine children"),
    ),
    self_check=(
        Step(Text("For each child, say what change it would absorb without its siblings noticing. If none, merge it.")),
        Step(Text("Run the check."), (AbstractOp.CHECK,)),
    ),
    example=WorkedExample(
        situation=Text("A billing component that computes invoices."),
        result={
            DesignPath("needs/billed-correctly.md"):
                "---\nkind: need\nstakeholder: Customer\nsignal: Invoice disputes\n---\nA customer is charged what "
                "they agreed to.\n",
            DesignPath("components/billing.md"):
                "---\nkind: component\nrealizes: Produce the invoice for a billing period\nsolution: Price usage, "
                "then apply tax\nserves: [billed-correctly]\nstatus: specified\n---\n## Acceptance criteria\n- AC1: "
                "When a period closes, billing shall produce one invoice per account.\n\n## Decisions\n### Price, then "
                "tax\n- Chose: two stages, pricing and tax\n- Over: one calculator\n- Because: tax rules change on a "
                "different schedule from price plans\n",
            DesignPath("components/billing/pricing.md"):
                "---\nkind: component\nrealizes: Price an account's usage for a period\nsolution: Rate tables\n"
                "hides: How price plans are represented\nserves: [billed-correctly]\nstatus: specified\n---\n## Acceptance criteria\n- AC1: The "
                "pricing shall charge each unit of usage at its plan's rate.\n",
            DesignPath("components/billing/tax.md"):
                "---\nkind: component\nrealizes: Compute tax owed on a priced invoice\nsolution: Jurisdiction rules "
                "as data\nhides: How tax rules are evaluated\nserves: [billed-correctly]\nuses: [pricing]\nstatus: specified\n---\n## Acceptance "
                "criteria\n- AC1: When an invoice is priced, the tax shall follow the customer's jurisdiction.\n",
        },
        lesson=Text("Each child hides one thing that changes on its own schedule; the matrix is decoupled "
                    "(tax uses pricing), so pricing can be built first."),
    ),
)
