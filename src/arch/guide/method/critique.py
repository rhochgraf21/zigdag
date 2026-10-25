"""Critiquing design text: an independent reviewer judges it against the rubric, and every finding gets an answer."""

from __future__ import annotations

from arch.guide.method.model import AbstractOp, Method, MethodName, Step, WorkedExample
from arch.model.ids import DesignPath, Text

CRITIQUE = Method(
    name=MethodName.CRITIQUE,
    title=Text("Have design text critiqued"),
    when=Text("Before marking a part specified, after its needs, requirements, criteria or solution change, or when "
              "the check asks for a critique (Q001)."),
    inputs=(Text("The nodes that wait for a critic"), Text("A reviewer that did not write the text")),
    steps=(
        Step(Text("See which nodes wait for a critic, and get the request for them."), (AbstractOp.CRITIQUE,)),
        Step(Text("Give the request to a reviewer that did not write the text and starts with no other context: a "
                  "fresh agent, or a colleague. Independence is the point. An author reading their own text sees what "
                  "they meant, not what they wrote.")),
        Step(Text("Record the reviewer's answer exactly as given. Only findings that quote the text and ask a rubric "
                  "question are kept."), (AbstractOp.CRITIQUE,)),
        Step(Text("Read each finding. Fix the text, or answer the finding with a reason. A declined finding is not a "
                  "failure: say why, so the next reader learns from it."), (AbstractOp.RESPOND,)),
        Step(Text("When the reviewer missed something that was found later, raise it as an escape. Its countermeasure "
                  "is usually a sharper question or a new example in the rubric."), (AbstractOp.RAISE,)),
    ),
    exit_criteria=(
        Text("No node under a critique policy waits for a critic"),
        Text("Every critic finding is fixed, or answered with a reason"),
    ),
    self_check=(Step(Text("Run the check. It asks again for any node whose text changed since its critique."),
                     (AbstractOp.CHECK,)),),
    example=WorkedExample(
        situation=Text("The critic quoted \"and tell the author what is still to do\" in the requirement of a review "
                       "session, and asked: does it ask for more than one function?"),
        result={
            DesignPath("needs/fix-what-reviewers-ask.md"):
                "---\nkind: need\nstakeholder: Author of a change\nsignal: Change requests still open at merge\n---\n"
                "An author knows which change requests are still open.\n",
            DesignPath("components/review.md"):
                "---\nkind: component\nrealizes: Let a person review a change one page at a time\nsolution: Review "
                "pages with verdicts kept against each page's content\nserves: [fix-what-reviewers-ask]\nstatus: "
                "specified\n---\n## Acceptance criteria\n- AC1: When a reviewer requests changes, the author shall see "
                "the request.\n",
            DesignPath("components/review/verdicts.md"):
                "---\nkind: component\nrealizes: Keep a reviewer's verdicts on review pages\nsolution: A local file per "
                "branch\nhides: Where verdicts are stored\nserves: [fix-what-reviewers-ask]\nstatus: specified\n---\n## Acceptance criteria\n- AC1: When "
                "a page changes after its verdict, the verdict shall count as stale.\n",
            DesignPath("components/review/feedback.md"):
                "---\nkind: component\nrealizes: Tell the author which change requests are still open\nsolution: A "
                "list built from the verdicts, blocking requests first\nhides: How requests are ranked\nuses: "
                "[verdicts]\nserves: [fix-what-reviewers-ask]\nstatus: specified\n---\n## Acceptance criteria\n- AC1: When a change request is answered, "
                "the list shall no longer show it.\n",
        },
        lesson=Text("The second function got a part of its own, so keeping verdicts and telling the author can now "
                    "change apart."),
    ),
)
