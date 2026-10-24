"""Eliciting needs: the real problem, in the stakeholder's terms, with no solution inside it."""

from __future__ import annotations

from arch.guide.method.model import AbstractOp, Method, MethodName, Step, WorkedExample
from arch.model.ids import DesignPath, Text

ELICIT_NEEDS = Method(
    name=MethodName.ELICIT_NEEDS,
    title=Text("Elicit needs"),
    when=Text("Starting a project or feature, or when a request arrives phrased as a solution (\"add a cache\", "
              "\"we need a dashboard\"), or when a component traces to no need."),
    inputs=(Text("The request or idea, as stated"), Text("Who asked, and who else is affected")),
    steps=(
        Step(Text("List the stakeholders: who uses the result, who pays for it, who operates it, who is harmed when "
                  "it fails. A need without a stakeholder is a guess.")),
        Step(Text("For each stakeholder, ask what they are trying to get done and how they would know it was done. "
                  "The second answer is the need's signal; if nobody can say, the need is not understood yet.")),
        Step(Text("Ask \"why?\" of every solution in the request until the answer stops being a solution "
                  "(\"a cache\" -> \"pages are slow\" -> \"shoppers leave before checkout\"). The need is the last "
                  "answer that still describes the stakeholder's world.")),
        Step(Text("Write each need as what must be true for the stakeholder: \"<stakeholder> can <outcome>\" or "
                  "\"<situation> does not happen\". No technology, component or product names; no verbs like "
                  "\"use\", \"store\" or \"display\" that presuppose a design.")),
        Step(Text("Record each need with its stakeholder and signal."), (AbstractOp.ADD_NEED,)),
        Step(Text("Connect needs to the top-level components that serve them, or note that no component does yet."),
             (AbstractOp.LINK,)),
    ),
    exit_criteria=(
        Text("Every need names a stakeholder and a signal"),
        Text("No need contains a solution term"),
        Text("Every top-level component serves at least one need, and every need is served"),
    ),
    self_check=(
        Step(Text("Read each need aloud to the stakeholder in their words; if they would not recognise it, rewrite it.")),
        Step(Text("Run the check; statement rules flag solution terms and vague words."), (AbstractOp.CHECK,)),
    ),
    example=WorkedExample(
        situation=Text("Request: \"Add Redis caching to the product pages.\""),
        result={
            DesignPath("needs/browse-without-waiting.md"):
                "---\nkind: need\nstakeholder: Shopper on a phone\nsignal: Share of product views that reach "
                "\"add to cart\"; time until the page is usable\n---\nA shopper can see a product and decide "
                "before losing interest.\n",
            DesignPath("components/shop.md"):
                "---\nkind: component\nrealizes: Let shoppers find and buy products\nsolution: A web shop\n"
                "serves: [browse-without-waiting]\nstatus: draft\n---\n## Acceptance criteria\n- AC1: When a "
                "shopper opens a product, the shop shall show it within one second at the 95th percentile.\n",
        },
        lesson=Text("Caching is one possible solution; the need is about the shopper deciding. Other solutions "
                    "(smaller pages, prerendering) now compete on equal terms."),
    ),
)
