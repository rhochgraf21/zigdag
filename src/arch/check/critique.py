"""An independent critic judges design text against a rubric; arch accepts only what the critic can quote.

Realizes arch.check.critique. arch never calls a model. It writes the request: the rubric, and each node's
text with only the context a critic needs. It checks the answer: every finding must name a question the
rubric asks of that kind of text, and quote words that really are in it. What passes becomes stored
findings from a critic, plus the answer to each reviewed node's critique question (rule Q001). Q001 is
keyed by the node's content, so a node is critiqued again whenever its text changes.

Calibration uses the same path: each question carries an example it should flag and one it should let
pass, and an answer about those examples is scored instead of stored.

Each question records the rubric version that added it. A node judged at its current text under an older
version is asked only the questions added since, so growing the rubric does not mean judging everything again.
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from typing import NewType

from arch.check.engine import Context, Finding, FindingIdentity, FindingKey, Kind, Rule, RuleId, Source, Station, Subject
from arch.check.ledger import Answer, Ledger, digest_of
from arch.model import codec
from arch.model.graph import Graph
from arch.model.ids import ComponentId, Text, parent_of
from arch.model.policy import Critique as Requirement
from arch.model.schema import Kind as NodeKind
from arch.realize.facts import Facts
from arch.realize.mapping import map_units

RUBRIC_VERSION = Text("2")  # the newest question's `since`; raise both when questions are added or change meaning
Version = NewType("Version", int)
QuestionId = NewType("QuestionId", str)
Tally = NewType("Tally", int)  # examples counted in calibration
AnswerText = NewType("AnswerText", str)  # a critic's answer, as JSON
CALIBRATION = "cal:"  # prefix of the subjects of calibration examples


class Part(enum.Enum):
    """What a question looks at."""

    NEED = "need"
    REQUIREMENT = "requirement"  # a component's `realizes`
    CRITERION = "criterion"
    SOLUTION = "solution"  # a component's `solution` and `hides`
    DECISION = "decision"
    CONSTRAINT = "constraint"
    INTERFACE = "interface"  # a component's public functions, classes and fields, as the code declares them

    @property
    def node_kind(self) -> NodeKind:
        return {Part.NEED: NodeKind.NEED, Part.CONSTRAINT: NodeKind.CONSTRAINT}.get(self, NodeKind.COMPONENT)


@dataclass(frozen=True)
class Question:
    id: QuestionId
    part: Part
    station: Station
    ask: Text
    because: Text  # the principle behind the question
    flags: Text  # an example it should flag
    passes: Text  # an example it should let pass
    since: Version = Version(1)  # the rubric version that added it


def _q(id: str, part: Part, station: Station, ask: str, because: str, flags: str, passes: str, since: int = 1) -> Question:
    return Question(QuestionId(id), part, station, Text(ask), Text(because), Text(flags), Text(passes), Version(since))


RUBRIC: tuple[Question, ...] = (
    _q("need-names-solution", Part.NEED, Station.NEEDS,
       "Does the need name or presuppose a solution, such as a technology, a component, a screen or a stored record?",
       "A need says what must be true for the stakeholder. A solution inside it rules out better ones before anyone "
       "looks.",
       "Shoppers can see products quickly because pages are cached in Redis.",
       "A shopper can see a product and decide before losing interest."),
    _q("need-not-an-outcome", Part.NEED, Station.NEEDS,
       "Is the need written as an outcome in the stakeholder's world, one they would recognise as their own?",
       "A need in the builder's words describes a function, not why anyone wants it.",
       "The system processes orders in batches every hour.",
       "A shop owner knows by morning which orders shipped the day before."),
    _q("need-signal-unobservable", Part.NEED, Station.NEEDS,
       "Can the need's signal be observed or measured as written?",
       "The signal is how anyone will know the need is met. A signal nobody can observe makes the need uncheckable.",
       "signal: Users are happier",
       "signal: Share of product views that reach add to cart"),
    _q("requirement-two-functions", Part.REQUIREMENT, Station.REQUIREMENTS,
       "Does `realizes` ask for more than one function? Quote the second one.",
       "Each function needs its own design parameter. Two functions under one solution are coupled from the start.",
       "realizes: Keep a reviewer's verdicts, and tell the author what is still to do",
       "realizes: Keep a reviewer's verdicts on review pages"),
    _q("requirement-states-how", Part.REQUIREMENT, Station.REQUIREMENTS,
       "Does `realizes` say how the part works instead of what it must achieve?",
       "The requirement is the what and the solution is the how. Mixing them hides the choice and its alternatives.",
       "realizes: Store sessions in Redis",
       "realizes: Remember a user's session between requests"),
    _q("requirement-not-from-parent", Part.REQUIREMENT, Station.REQUIREMENTS,
       "Does the requirement follow from the parent's chosen solution, as something that solution needs?",
       "A child's requirement comes from its parent's design choice. One that does not follow belongs elsewhere, or "
       "the parent's solution is incomplete.",
       "parent solution: A checkout service. realizes: Recommend related products",
       "parent solution: A checkout service. realizes: Take payment for an order"),
    _q("criterion-adds-function", Part.CRITERION, Station.REQUIREMENTS,
       "Does the criterion require a function the requirement does not name, rather than a trigger, condition, output "
       "or range of the function it has? Quote the new function.",
       "A criterion pins down its requirement's function. A criterion that adds a function is a requirement without "
       "a solution of its own.",
       "realizes: Take payment for an order. AC3: When a payment succeeds, the checkout shall email a receipt.",
       "realizes: Take payment for an order. AC2: If the provider does not answer within 10 seconds, then the "
       "checkout shall decline without charging."),
    _q("criterion-undecidable", Part.CRITERION, Station.REQUIREMENTS,
       "Could a test decide the criterion, pass or fail, without asking anyone's opinion?",
       "A criterion that no test can decide yields no evidence.",
       "AC1: The page shall be easy to read.",
       "AC1: Each sentence on the page shall have at most 25 words."),
    _q("criterion-is-constraint", Part.CRITERION, Station.REQUIREMENTS,
       "Does the criterion limit how the part may be built, such as its tools, files, network or language, rather "
       "than what it does?",
       "A limit on every solution is a constraint. Written as a criterion, it hides from the other parts it binds.",
       "AC1: The page shall load no external resources.",
       "AC1: When the reviewer presses the right arrow key, the page shall show the next page."),
    _q("solution-misses-requirement", Part.SOLUTION, Station.SOLUTION,
       "Would the solution, as stated, achieve the requirement? If not, say what is missing.",
       "The design parameter must satisfy its requirement. A solution that covers only part of it leaves the rest "
       "with no owner.",
       "realizes: Take payment for an order. solution: A form that collects card numbers",
       "realizes: Take payment for an order. solution: A checkout service that charges the card through the payment "
       "provider and records the result"),
    _q("hides-no-decision", Part.SOLUTION, Station.SOLUTION,
       "Does `hides` name one decision that is likely to change and that the part keeps from the others?",
       "A part earns its boundary by hiding a decision. Something like implementation details hides nothing in "
       "particular.",
       "hides: Implementation details",
       "hides: Where sessions are stored"),
    _q("decision-straw-alternative", Part.DECISION, Station.SOLUTION,
       "Is the rejected alternative a real option that a competent designer could have chosen?",
       "A decision is only as good as the alternatives it beat. A straw alternative records no choice.",
       "Chose: a database. Over: storing everything on paper",
       "Chose: plain-text files in the repository. Over: a database service"),
    _q("decision-reason-restates", Part.DECISION, Station.SOLUTION,
       "Does `Because` give a reason, rather than restate the choice or praise it?",
       "The reason is what lets someone revisit the choice when circumstances change.",
       "Because: it is the better option",
       "Because: reviews happen in pull requests, and text files diff and merge there"),
    _q("criterion-contradicts-decision", Part.CRITERION, Station.REQUIREMENTS,
       "Does the criterion contradict a decision recorded on the same part?",
       "A criterion and a decision that disagree leave the part's behaviour undecided, and one of them is out of date.",
       "Decision: Chose: charge effects where the object was obtained. AC3: Calls that cannot be resolved shall yield "
       "unknown.",
       "Decision: Chose: charge effects where the object was obtained. AC3: When a call cannot be resolved, its effects "
       "shall be charged where the object was obtained.", since=2),
    _q("interface-flag-picks-behaviour", Part.INTERFACE, Station.INTERFACE,
       "Does a function take a flag or a mode that picks between different behaviours?",
       "A parameter that picks the behaviour hides several functions inside one, and every caller pays for all of them.",
       "def fetch(url: Url, cached: bool, retry: bool, verbose: bool) -> Page",
       "def fetch(url: Url, policy: FetchPolicy) -> Page", since=2),
    _q("interface-order-to-remember", Part.INTERFACE, Station.INTERFACE,
       "Must a caller call functions in a set order, such as init before run, for them to work?",
       "An order the caller must remember is an invalid state the types allow. A function can instead return the object "
       "that does the next step.",
       "def init() -> None; def connect() -> None; def run(job: Job) -> Result",
       "def connect(config: Config) -> Session; Session.run(self, job: Job) -> Result", since=2),
    _q("interface-leaks-storage", Part.INTERFACE, Station.INTERFACE,
       "Does the interface take or return a storage or library type, such as a database cursor or an ORM row, instead "
       "of a domain value?",
       "A storage type in the interface ties every caller to how the data is kept, so the part cannot change it.",
       "def orders(user: UserId) -> sqlite3.Cursor",
       "def orders(user: UserId) -> tuple[Order, ...]", since=2),
    _q("constraint-is-function", Part.CONSTRAINT, Station.REQUIREMENTS,
       "Does the constraint limit every solution, or is it a function in disguise that some part should realize?",
       "Constraints bound the design. A function belongs to a component with a solution of its own.",
       "The system shall send a weekly report to managers.",
       "arch never opens a network connection."),
)
_BY_ID = {q.id: q for q in RUBRIC}

INSTRUCTIONS: tuple[Text, ...] = tuple(Text(t) for t in (
    "You are an independent critic. You did not write this text and you have no stake in it.",
    "For each subject, ask every question for its kind of text. Raise a finding only when the answer shows a real "
    "defect. When in doubt, leave it out.",
    "Every finding must quote the exact words it is about, copied character for character from the subject's text "
    "or interface. Quote as little as identifies the problem.",
    "Write each message as one or two plain sentences: what is wrong, and why it matters. Put a concrete fix in hint.",
    "Do not comment on style, spelling, or anything the questions do not ask.",
    "List every subject you reviewed in reviewed, including the ones with no findings.",
    "When a subject lists its questions, ask only those: its text was judged against the others before.",
    "Interface questions look at the subject's interface: the public functions, classes and fields its code declares. "
    "A subject with no interface listed has none to judge yet.",
    "Answer with JSON only, in the answer format.",
))
ANSWER_FORMAT: Text = Text('{"critic": "<your name>", "rubric": "<the rubric version>", "reviewed": ["<subject>", ...], '
                           '"findings": [{"subject": "<subject>", "question": "<question id>", "quote": "<exact words>", '
                           '"message": "<what is wrong, and why>", "hint": "<how to fix it>"}]}')


def required(graph: Graph) -> tuple[Subject, ...]:
    """The nodes a constraint asks to have critiqued: components under a critique policy, and every need and
    constraint when the policy covers a top-level component."""
    components = [cid for cid in graph.ids() if graph.effective_policy(cid).critique is Requirement.REQUIRED]
    top = any(parent_of(c) is None for c in components)
    design = graph.design
    return tuple(Subject(s) for s in (*components, *(sorted(design.needs) if top else ()),
                                      *(sorted(design.constraints) if top else ())))


def version_for(kind: NodeKind) -> Version:
    """The rubric version for one kind of node: the newest question asked of it. A node is critiqued again only when
    its own kind gets new questions."""
    return max((q.since for q in RUBRIC if q.part.node_kind is kind), default=Version(1))


def kind_of(graph: Graph, subject: Subject) -> NodeKind:
    design = graph.design
    return NodeKind.NEED if subject in design.needs else NodeKind.CONSTRAINT if subject in design.constraints \
        else NodeKind.COMPONENT


def wanted(graph: Graph, subject: Subject) -> FindingIdentity:
    """The identity of the question "has this text been critiqued since it last changed?" for one node."""
    version = version_for(kind_of(graph, subject))
    return (RuleId("Q001"), subject, FindingKey(f"critique:{digest_of(graph, subject)}:v{version}"))


def asked_since(kind: NodeKind, version: Version) -> tuple[QuestionId, ...]:
    """The questions added for a kind of node after a version it was already judged with."""
    return tuple(q.id for q in RUBRIC if q.part.node_kind is kind and q.since > version)


def still_to_ask(graph: Graph, ledger: Ledger) -> dict[Subject, tuple[QuestionId, ...]]:
    """For each node a critic judged at its current text under an older rubric: only the questions added since.
    A node whose text changed is judged against every question again, so it is not listed."""
    judged: dict[Subject, Version] = {}
    for r in ledger.responses:
        if r.answer is not Answer.ANSWERED:
            continue
        for rule, subject, key in r.findings:
            digest, _, version = key.removeprefix("critique:").rpartition(":v")
            if rule == "Q001" and version.isdigit() and digest == digest_of(graph, subject):
                judged[subject] = max(judged.get(subject, Version(0)), Version(int(version)))
    out = {}
    for subject, version in judged.items():
        kind = kind_of(graph, subject)
        if version < version_for(kind):
            out[subject] = asked_since(kind, version)
    return out


def critique_wanted(ctx: Context) -> Iterator[Finding]:
    for subject in required(ctx.graph):
        _, _, key = wanted(ctx.graph, subject)
        yield Finding(subject, RuleId("Q001"), key, Kind.QUESTION,
                      Text("its text has not been judged by an independent critic since it last changed"),
                      Text("run `arch critique --request`, hand the request to a reviewer that did not write the text, "
                           "then `arch critique --record <answer>`"))


RULES: tuple[Rule, ...] = (
    Rule(RuleId("Q001"), Station.REQUIREMENTS, Text("design text is judged by an independent critic"), critique_wanted),
)


@dataclass(frozen=True)
class Piece:
    """One subject a critic reviews: its text as written, and what it needs to know around it."""

    subject: Subject
    kind: NodeKind
    text: Text
    context: tuple[tuple[Text, Text], ...] = ()
    interface: Text = Text("")  # for a component with code: its public functions, classes and fields
    asked: tuple[QuestionId, ...] = ()  # when set, only these questions: the others were answered for this text


class Purpose(enum.Enum):
    DESIGN = "design"  # judge the design; accepted findings are stored
    CALIBRATION = "calibration"  # judge the rubric's own examples; the answer is scored


@dataclass(frozen=True)
class Request:
    pieces: tuple[Piece, ...]
    purpose: Purpose

    def to_json(self) -> AnswerText:
        whole = {p.kind for p in self.pieces if not p.asked}  # these subjects are judged against every question
        some = {q for p in self.pieces for q in p.asked}
        questions = [q for q in RUBRIC if q.part.node_kind in whole or q.id in some]
        blind = self.purpose is Purpose.CALIBRATION  # the examples are what is judged, so they must not be shown
        doc = {
            "rubric": RUBRIC_VERSION, "purpose": self.purpose.value,
            "instructions": list(INSTRUCTIONS),
            "questions": [{"id": q.id, "part": q.part.value, "ask": q.ask, "because": q.because,
                           **({} if blind else {"flags": q.flags, "passes": q.passes})} for q in questions],
            "subjects": [{"subject": p.subject, "kind": p.kind.value, "text": p.text, "context": dict(p.context),
                          **({"interface": p.interface} if p.interface else {}),
                          **({"questions": list(p.asked)} if p.asked else {})} for p in self.pieces],
            "answer_format": ANSWER_FORMAT,
        }
        return AnswerText(json.dumps(doc, indent=2, ensure_ascii=False))


def request(graph: Graph, subjects: tuple[Subject, ...], facts: Facts | None = None,
            asked: Mapping[Subject, tuple[QuestionId, ...]] | None = None) -> Request:
    """What a critic needs: each node's text, its near context, its interface when the code is known, and, for a node
    judged before at its current text, only the questions added since."""
    interfaces = _interfaces(graph, facts) if facts is not None else {}
    asked = asked or {}
    pieces = tuple(replace(p, interface=interfaces.get(p.subject, Text("")), asked=asked.get(p.subject, ()))
                   for s in subjects if (p := _piece(graph, s)) is not None)
    return Request(pieces, Purpose.DESIGN)


def _interfaces(graph: Graph, facts: Facts) -> dict[Subject, Text]:
    """Each component's public declarations, as signatures, from the units that belong to it directly."""
    mapping = map_units(graph, facts)
    out: dict[Subject, list[str]] = {}
    for sym in facts.symbols:
        cid = mapping.component_of.get(sym.unit)
        if cid is not None:
            out.setdefault(Subject(cid), []).append(f"{sym.unit}: {sym.signature}")
    return {k: Text("\n".join(v[:_INTERFACE_LINES])) for k, v in out.items()}


_INTERFACE_LINES = 80  # enough to judge an interface; a larger one is a finding in itself


def calibration_request() -> Request:
    pieces = tuple(Piece(Subject(f"{CALIBRATION}{q.id}:{side}"), q.part.node_kind, example)
                   for q in RUBRIC for side, example in (("flags", q.flags), ("passes", q.passes)))
    return Request(pieces, Purpose.CALIBRATION)


def _piece(graph: Graph, subject: Subject) -> Piece | None:
    design = graph.design
    for kind, nodes in ((NodeKind.COMPONENT, design.components), (NodeKind.NEED, design.needs),
                        (NodeKind.CONSTRAINT, design.constraints)):
        if subject in nodes:
            text = Text(design.sources.get(codec.path_of(kind, subject), ""))
            return Piece(subject, kind, text, tuple(_context(graph, kind, subject)))
    return None


def _context(graph: Graph, kind: NodeKind, subject: Subject) -> Iterator[tuple[Text, Text]]:
    if kind is NodeKind.CONSTRAINT:
        c = graph.design.constraints[subject]
        yield Text("rule in plain words"), c.policy.describe()
        return
    if kind is not NodeKind.COMPONENT:
        return
    cid = ComponentId(subject)
    parent = parent_of(cid)
    if parent is not None and parent in graph:
        yield Text("parent requirement"), graph[parent].realizes
        yield Text("parent solution"), graph[parent].solution
        siblings = [f"{s}: {graph[s].realizes}" for s in graph.children(parent) if s != cid]
        if siblings:
            yield Text("siblings"), Text("; ".join(siblings))
    needs = [f"{n}: {graph.design.needs[n].statement}" for n in graph[cid].serves if n in graph.design.needs]
    if needs:
        yield Text("needs it serves"), Text(" ".join(needs))


@dataclass(frozen=True)
class Raised:
    subject: Subject
    question: QuestionId
    quote: Text
    message: Text
    hint: Text


@dataclass(frozen=True)
class CriticAnswer:
    """A critic's answer, read from JSON."""

    critic: Text
    rubric: Text
    reviewed: tuple[Subject, ...]
    raised: tuple[Raised, ...]

    @staticmethod
    def parse(text: AnswerText) -> CriticAnswer:
        try:
            doc = json.loads(text)
            raised = tuple(Raised(Subject(str(f["subject"])), QuestionId(str(f["question"])), Text(str(f["quote"])),
                                  Text(str(f["message"])), Text(str(f.get("hint") or ""))) for f in doc.get("findings", []))
            return CriticAnswer(Text(str(doc["critic"])), Text(str(doc.get("rubric", ""))),
                          tuple(Subject(str(s)) for s in doc["reviewed"]), raised)
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"not a critic's answer in the answer format: {e}") from None

    @property
    def purpose(self) -> Purpose:
        return Purpose.CALIBRATION if self.reviewed and all(s.startswith(CALIBRATION) for s in self.reviewed) \
            else Purpose.DESIGN


@dataclass(frozen=True)
class Verdict:
    """What arch accepts from an answer, and why it refuses the rest."""

    findings: tuple[Finding, ...]
    reviewed: tuple[Subject, ...]
    refused: tuple[Text, ...]


def judge(answer: CriticAnswer, graph: Graph, facts: Facts | None = None,
          asked: Mapping[Subject, tuple[QuestionId, ...]] | None = None) -> Verdict:
    """Accept a finding only if it names a question asked of that text and quotes words that are in it."""
    if answer.rubric != RUBRIC_VERSION:
        return Verdict((), (), (Text(f"the answer is for rubric {answer.rubric or '?'}, not {RUBRIC_VERSION}"),))
    pieces = {p.subject: p for p in request(graph, answer.reviewed, facts, asked).pieces}
    reviewed = tuple(s for s in answer.reviewed if s in pieces)
    refused = [Text(f"{s}: no such design node") for s in answer.reviewed if s not in pieces]
    accepted = []
    for r in answer.raised:
        reason = _refusal(r, pieces)
        if reason:
            refused.append(Text(f"{r.subject} {r.question}: {reason}"))
            continue
        q = _BY_ID[r.question]
        accepted.append(Finding(r.subject, RuleId(r.question), FindingKey(""), Kind.QUESTION, r.message, r.hint,
                                station=q.station, source=Source.CRITIC, evidence=r.quote))
    return Verdict(tuple(accepted), reviewed, tuple(refused))


def _refusal(r: Raised, pieces: dict[Subject, Piece]) -> str | None:
    piece = pieces.get(r.subject)
    q = _BY_ID.get(r.question)
    if piece is None:
        return "the subject was not reviewed"
    if q is None:
        return "the rubric has no such question"
    if q.part.node_kind is not piece.kind:
        return f"that question is about a {q.part.value}, and this is a {piece.kind.value}"
    if piece.asked and q.id not in piece.asked:
        return "that question was not asked of this subject"
    if not r.message.strip():
        return "the finding says nothing"
    if not r.quote.strip() or _squash(r.quote) not in _squash(f"{piece.text}\n{piece.interface}"):
        return f"the quote is not in the text: \"{r.quote}\""
    return None


def repeats(new: Finding, old: Finding) -> bool:
    """Whether a critic's finding says again what an earlier one said: the same question about the same subject,
    with one quote inside the other. A repeat is not recorded, so an answered finding stays answered."""
    if (new.subject, new.rule) != (old.subject, old.rule) or not new.evidence or not old.evidence:
        return False
    a, b = _squash(new.evidence), _squash(old.evidence)
    return a in b or b in a


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Agreement:
    """How a critic did on one question's examples."""

    question: QuestionId
    right: Tally
    asked: Tally


def score(answer: CriticAnswer) -> tuple[Agreement, ...]:
    """For calibration: did the critic flag each question's flag example, and leave its pass example alone?"""
    flagged = {(r.subject, r.question) for r in answer.raised}
    out = []
    for q in RUBRIC:
        right = asked = 0
        for side in ("flags", "passes"):
            subject = Subject(f"{CALIBRATION}{q.id}:{side}")
            if subject in answer.reviewed:
                asked += 1
                right += ((subject, q.id) in flagged) == (side == "flags")
        if asked:
            out.append(Agreement(q.id, Tally(right), Tally(asked)))
    return tuple(out)


__all__ = ["RUBRIC", "RUBRIC_VERSION", "RULES", "Agreement", "CriticAnswer", "AnswerText", "Part", "Piece", "Purpose",
           "Question", "QuestionId", "Request", "Tally", "Verdict", "Version", "asked_since", "kind_of", "still_to_ask", "version_for", "calibration_request", "judge", "repeats", "request", "required", "score", "wanted"]
