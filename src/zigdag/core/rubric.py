"""The critique rubric (DESIGN2 §2.7, §10): what a critic asks of each kind of entry, about what checks cannot see.

Every question has the rubric version it arrived in. An entry critiqued under an older version, and unchanged
since, is asked only the newer questions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from zigdag.core.record.entries import EntryKind

RUBRIC_VERSION = 1


@dataclass(frozen=True)
class Question:
    id: str
    ask: str
    since: int = 1


RUBRIC: Mapping[EntryKind, tuple[Question, ...]] = {
    EntryKind.JOB: (
        Question("job-real", "Is this something the performer is trying to get done, whatever product they use?"),
        Question("job-level", "Is it the whole job, not a step inside a bigger job, and not a way of doing one?"),
        Question("performer-real", "Is the performer a real kind of person or agent who does this job?"),
    ),
    EntryKind.OUTCOME: (
        Question("outcome-used", "Would the performer use this measure to judge whether the job went well?"),
        Question("outcome-measurable", "Is it clear what would be counted or timed to measure it?"),
        Question("outcome-stable", "Does it stay true whichever solution is used, naming no solution?"),
        Question("outcome-distinct", "Is it distinct from the job's other outcomes, rather than the same one reworded?"),
    ),
    EntryKind.FR: (
        Question("fr-function", "Is the ubiquitous statement one function, and the right one for the outcomes above it?"),
        Question("fr-conditions", "Does each other statement pin down that function, without adding a second one?"),
        Question("fr-decidable", "Could a test decide each statement, and is each true of what the system must do?"),
        Question("fr-complete", "Do the FRs below it, together, achieve its function, with nothing missing or extra?"),
        Question("fr-design", "Is the code that performs it the simplest choice among the alternatives?"),
    ),
    EntryKind.CONSTRAINT: (
        Question("constraint-limit", "Is it a limit on how the design may be built, rather than a function?"),
        Question("constraint-why", "Does the outcome it serves explain why the limit exists?"),
        Question("constraint-place", "Is it placed on the FR whose whole subtree must keep it, no higher and no lower?"),
        Question("constraint-except", "Is each excepted piece of code a real exception, not a sign the limit is wrong?"),
    ),
    EntryKind.PROCESS_VARIABLE: (
        Question("process-how", "Does it change how the code is made or checked, rather than what the system does?"),
        Question("process-why", "Does the outcome it serves explain why this way of working pays off?"),
    ),
    EntryKind.TUNING: (
        Question("tuning-justified", "Is the change to the built-in rule justified, and its reason written down?"),
        Question("tuning-except", "Is each excepted piece of code a real exception, rather than debt left unnamed?"),
    ),
    EntryKind.PLACEMENT: (
        Question("placement-home", "Is this code the right home for the design parameter, holding nothing that "
                                   "belongs to another one?"),
    ),
}


def still_to_ask(kind: EntryKind, asked_under: int | None) -> tuple[Question, ...]:
    """The questions for an entry: all of them, or only those newer than the version it was critiqued under."""
    return tuple(q for q in RUBRIC.get(kind, ()) if asked_under is None or q.since > asked_under)
