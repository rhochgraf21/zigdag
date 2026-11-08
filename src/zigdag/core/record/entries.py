"""The record as entries (DESIGN2 §7.7): each job, outcome, FR, constraint, process variable, tuning and physical
entry, with a digest of its content. Critiques and approvals are for one digest; when the content changes, so does
the digest, and they no longer count.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Mapping
from dataclasses import dataclass

from zigdag.core.findings import Digest, Span, digest_of
from zigdag.core.record.builtins import BUILT_INS
from zigdag.core.record.model import (
    Build,
    CheckUse,
    CodeRule,
    Domain,
    Excepted,
    Record,
    Validation,
    Verification,
    Workflow,
)


class EntryKind(enum.Enum):
    JOB = "job"
    OUTCOME = "outcome"
    FR = "FR"
    CONSTRAINT = "constraint"
    PROCESS_VARIABLE = "process variable"
    TUNING = "tuning"
    PLACEMENT = "physical entry"


PHYSICAL_PREFIX = "physical:"  # a physical entry is named after its FR: physical:mojo2verus.cli


@dataclass(frozen=True)
class Entry:
    kind: EntryKind
    name: str  # what a log event's `on` names
    fields: Mapping[str, object]  # what it says, as plain values
    span: Span
    scope: str | None  # the FR it is about, for gates placed on part of the tree; None for the customer domain
    domain: Domain

    @property
    def content(self) -> str:
        return json.dumps(self.fields, sort_keys=True, ensure_ascii=False)

    @property
    def digest(self) -> Digest:
        return digest_of(self.kind.value, self.name, self.content)


def _excepted(excepted: tuple[Excepted, ...]) -> list[str]:
    return [str(e.code) + (f"  # {e.reason}" if e.reason else "") for e in excepted]


def _check(use: CheckUse) -> dict[str, object]:
    return {"check": use.kind.value, "with": {k: v.value for k, v in sorted(use.params.items())},
            "except": _excepted(use.excepted)}


def entries(record: Record) -> dict[str, Entry]:
    """Every entry the record holds, by the name a log event uses for it."""
    out: dict[str, Entry] = {}
    for job in record.jobs:
        if not job.built_in:
            out[job.name] = Entry(EntryKind.JOB, job.name, {"job": job.job.text, "performer": job.performer.text},
                                  job.job.span, None, Domain.CUSTOMER)
        for o in job.outcomes:
            if not o.sentence.span.built_in:
                out[str(o.ref)] = Entry(EntryKind.OUTCOME, str(o.ref), {"outcome": o.sentence.text}, o.sentence.span,
                                        None, Domain.CUSTOMER)
    for name, fr in record.frs.items():
        out[name] = Entry(EntryKind.FR, name, {
            "serves": sorted(str(s.value) for s in fr.serves),
            "statements": {s.ref.statement: s.sentence.text for s in fr.statements},
        }, fr.span, name, Domain.FUNCTIONAL)
    for name, c in record.constraints.items():
        fields: dict[str, object] = {"on": c.on.value, "serves": sorted(str(s.value) for s in c.serves),
                                     "reason": c.reason}
        fields |= _check(c.check) if c.check else {"statement": c.statement.text if c.statement else None}
        out[name] = Entry(EntryKind.CONSTRAINT, name, fields, c.span, c.on.value, Domain.FUNCTIONAL)
    for name, v in record.process.items():
        fields = {"on": v.on.value, "serves": sorted(str(s.value) for s in v.serves), "reason": v.reason}
        k = v.kind
        if isinstance(k, CodeRule):
            fields |= {"kind": "code-rule", **_check(k.check)}
        elif isinstance(k, Verification):
            fields |= {"kind": "verification", "evidence": k.evidence.value, "report": k.report}
        elif isinstance(k, Validation):
            fields |= {"kind": "validation", "measures": str(k.measures.value), "report": k.report}
        elif isinstance(k, Build):
            fields |= {"kind": "build", "step": k.step, "produces": list(k.produces)}
        elif isinstance(k, Workflow):
            fields |= {"kind": "workflow", "gate": k.gate.value}
        out[name] = Entry(EntryKind.PROCESS_VARIABLE, name, fields, v.span, v.on.value, Domain.PROCESS)
    for name, t in record.tunings.items():
        out[name] = Entry(EntryKind.TUNING, name, {
            "with": {k: v.value for k, v in sorted(t.params.items())}, "except": _excepted(t.excepted),
            "on": t.on.value if t.on else None, "off": t.off, "reason": t.reason,
        }, t.span, t.on.value if t.on else None, BUILT_INS[name].domain if name in BUILT_INS else Domain.FUNCTIONAL)
    for name, p in record.placements.items():
        key = PHYSICAL_PREFIX + name
        out[key] = Entry(EntryKind.PLACEMENT, key, {"units": [str(u.value) for u in p.units]}, p.span, name,
                         Domain.PHYSICAL)
    return out
