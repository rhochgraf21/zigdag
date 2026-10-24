"""Reviewing a design change: intent first, then design, structure, policy, and evidence last."""

from __future__ import annotations

from arch.guide.method.model import AbstractOp, Method, MethodName, Step, WorkedExample
from arch.model.ids import DesignPath, Text

REVIEW_DESIGN_DIFF = Method(
    name=MethodName.REVIEW_DESIGN_DIFF,
    title=Text("Review a design change"),
    when=Text("Before approving a change that touches design files, or a code change whose components changed."),
    inputs=(Text("The revision to compare with (usually the merge base)"),),
    steps=(
        Step(Text("Read the design diff, grouped by kind of change."), (AbstractOp.DIFF,)),
        Step(Text("Intent: do the new or changed needs and requirements describe the real problem? Is each criterion "
                  "decidable by a test? Stop here if not; nothing below matters.")),
        Step(Text("Design: is each new solution's choice recorded with what it was chosen over and why? Does each "
                  "new component hide one secret?")),
        Step(Text("Structure: are new uses justified by the requirement? Is the matrix still free of coupling?"),
             (AbstractOp.MATRIX, AbstractOp.PLAN)),
        Step(Text("Policy: do constraint changes loosen anything? Loosening needs a decision.")),
        Step(Text("Evidence: are the new criteria linked to tests that pass?"), (AbstractOp.CHECK, AbstractOp.CONTEXT)),
        Step(Text("Give the verdict with reasons, by layer.")),
    ),
    exit_criteria=(Text("Every intent change is justified or sent back"), Text("No unexplained coupling or loosening")),
    self_check=(Step(Text("Run the check on the changed design."), (AbstractOp.CHECK,)),),
    example=WorkedExample(
        situation=Text("A change adds a component that realizes \"Store sessions in Redis\"."),
        result={
            DesignPath("needs/stay-signed-in.md"):
                "---\nkind: need\nstakeholder: Returning user\nsignal: Sign-ins per visit\n---\nA returning user "
                "does not have to sign in again during a working day.\n",
            DesignPath("components/app.md"):
                "---\nkind: component\nrealizes: Serve signed-in users\nsolution: A web app\nserves: "
                "[stay-signed-in]\nstatus: draft\n---\n## Acceptance criteria\n- AC1: The app shall keep a user "
                "signed in for 10 hours after their last request.\n",
            DesignPath("components/app/sessions.md"):
                "---\nkind: component\nrealizes: Remember a user's session between requests\nsolution: A session "
                "store\nhides: Where sessions are stored\nserves: [stay-signed-in]\nstatus: draft\n---\n## Acceptance criteria\n- AC1: When a "
                "user returns within 10 hours, the sessions shall restore their identity.\n",
        },
        lesson=Text("The review sent the requirement back: \"in Redis\" is the solution, so it moved to `hides`; the "
                    "requirement now says what must happen."),
    ),
)
