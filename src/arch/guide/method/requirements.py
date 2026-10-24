"""Writing requirements: one function per requirement, criteria that a test can decide."""

from __future__ import annotations

from arch.guide.method.model import AbstractOp, Method, MethodName, Step, WorkedExample
from arch.model.ids import DesignPath, Text

WRITE_REQUIREMENTS = Method(
    name=MethodName.WRITE_REQUIREMENTS,
    title=Text("Write requirements and acceptance criteria"),
    when=Text("Adding or changing what a component realizes, or when checks flag compound, vague or "
              "non-EARS statements."),
    inputs=(Text("The need or parent requirement this one refines"), Text("The component it will belong to")),
    steps=(
        Step(Text("State the functional requirement as verb + object + qualifier, about what must happen, not how: "
                  "\"Compute tax owed for an order under jurisdiction rules\".")),
        Step(Text("One function per requirement. If it joins two actions with \"and\", it is two requirements; "
                  "split it, usually into two components or two criteria.")),
        Step(Text("Write acceptance criteria in EARS form, each decidable by a test: ubiquitous (\"The <part> "
                  "shall ...\"), event (\"When <trigger>, the <part> shall ...\"), state (\"While <state>, ...\"), "
                  "unwanted behaviour (\"If <condition>, then the <part> shall ...\"), optional (\"Where <feature>, "
                  "...\").")),
        Step(Text("Replace every vague word (fast, simple, robust, user-friendly, scalable) with a number or an "
                  "observable condition.")),
        Step(Text("Add the criteria, then link each to the test or contract that will check it."),
             (AbstractOp.ADD_CRITERION, AbstractOp.SET_FIELD)),
    ),
    exit_criteria=(
        Text("Each requirement is a single function, free of solution terms"),
        Text("Each criterion contains \"shall\", names its trigger or condition, and is measurable"),
    ),
    self_check=(
        Step(Text("For each criterion, name the test that would fail if it were violated; if you cannot, rewrite it.")),
        Step(Text("Run the check; statement rules flag compound, vague and non-EARS statements."), (AbstractOp.CHECK,)),
    ),
    example=WorkedExample(
        situation=Text("Draft: \"The checkout should be fast and handle payments and receipts.\""),
        result={
            DesignPath("needs/pay-with-confidence.md"):
                "---\nkind: need\nstakeholder: Shopper\nsignal: Abandoned checkouts\n---\nA shopper can pay and "
                "know the payment went through.\n",
            DesignPath("components/checkout.md"):
                "---\nkind: component\nrealizes: Take payment for an order\nsolution: A checkout service\n"
                "serves: [pay-with-confidence]\nstatus: draft\n---\n## Acceptance criteria\n- AC1: When a shopper "
                "submits a valid card, the checkout shall confirm or decline within 3 seconds.\n- AC2: If the payment "
                "provider does not answer within 10 seconds, then the checkout shall decline without charging.\n",
        },
        lesson=Text("\"Fast\" became a number; receipts were split out as their own requirement elsewhere; the failure "
                    "case got its own criterion."),
    ),
)
