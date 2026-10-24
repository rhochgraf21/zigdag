"""Resolving coupling: state the contradiction, then separate (TRIZ) using what exists (ASIT)."""

from __future__ import annotations

from arch.guide.method.model import AbstractOp, Method, MethodName, Step, WorkedExample
from arch.model.ids import DesignPath, Text

RESOLVE_COUPLING = Method(
    name=MethodName.RESOLVE_COUPLING,
    title=Text("Resolve coupling"),
    when=Text("A matrix is coupled (check rule S005), or components keep changing together without a declared "
              "dependency (hidden coupling in the observed matrix)."),
    inputs=(Text("The coupled set, and the parent whose matrix shows it"),),
    steps=(
        Step(Text("See the coupling and what is observed in code and history."),
             (AbstractOp.MATRIX, AbstractOp.OBSERVED_MATRIX, AbstractOp.CONTEXT)),
        Step(Text("State it as a contradiction: \"making A <better> makes B <worse>\". Name what each side needs "
                  "from the other.")),
        Step(Text("Try separation, in this order. In structure: move the shared part down into a new child both can "
                  "use, or up into the parent. By level: let the lower part define the interface the upper one "
                  "implements (dependency inversion). In time: one side only needs the other at a later stage, so "
                  "pass data, not a reference. By condition: split the behaviour that needs the other side into its "
                  "own component.")),
        Step(Text("Prefer what already exists (ASIT closed world): give an existing component the shared function "
                  "before adding a new one; remove a dependency before adding an abstraction.")),
        Step(Text("Make the change."), (AbstractOp.ADD_COMPONENT, AbstractOp.MOVE, AbstractOp.LINK, AbstractOp.UNLINK)),
        Step(Text("Record what was chosen and why, with `Previously:` describing the coupled shape."),
             (AbstractOp.ADD_DECISION,)),
        Step(Text("If it truly cannot be resolved now, accept it explicitly on the parent with a decision saying what "
                  "would resolve it later."), (AbstractOp.SET_FIELD, AbstractOp.ADD_DECISION)),
    ),
    exit_criteria=(Text("The matrix is decoupled, or the coupling is accepted with a decision"),),
    self_check=(
        Step(Text("Check that no new cycle appeared one level up."), (AbstractOp.MATRIX,)),
        Step(Text("Run the check."), (AbstractOp.CHECK,)),
    ),
    example=WorkedExample(
        situation=Text("orders uses payments to charge, and payments uses orders to look up totals: coupled."),
        result={
            DesignPath("needs/orders-paid.md"):
                "---\nkind: need\nstakeholder: Merchant\nsignal: Orders shipped unpaid\n---\nA merchant ships only "
                "orders that were paid for.\n",
            DesignPath("components/shop.md"):
                "---\nkind: component\nrealizes: Sell products\nsolution: Orders paid through a payment step\n"
                "serves: [orders-paid]\nstatus: specified\n---\n## Acceptance criteria\n- AC1: When an order is "
                "placed, the shop shall ship it only after payment succeeds.\n\n## Decisions\n### Payments receive "
                "the amount\n- Chose: orders pass the amount to payments\n- Over: payments looking up the order\n"
                "- Because: payments only needs a number, not the order (separation in time: data, not a reference)\n"
                "- Previously: orders and payments used each other\n",
            DesignPath("components/shop/orders.md"):
                "---\nkind: component\nrealizes: Track an order from placement to shipping\nsolution: Order "
                "records with states\nhides: Order lifecycle rules\nserves: [orders-paid]\nuses: [payments]\nstatus: specified\n---\n## "
                "Acceptance criteria\n- AC1: When payment succeeds, the order shall move to ready to ship.\n",
            DesignPath("components/shop/payments.md"):
                "---\nkind: component\nrealizes: Charge an amount to a payment method\nsolution: A payment "
                "provider client\nhides: Which provider is used\nserves: [orders-paid]\nstatus: specified\n---\n## Acceptance criteria\n"
                "- AC1: When asked to charge an amount, payments shall report success or a decline reason.\n",
        },
        lesson=Text("Payments never needed the order, only its amount; passing data removed the cycle without a new "
                    "component."),
    ),
)
