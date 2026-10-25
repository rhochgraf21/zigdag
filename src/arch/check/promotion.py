"""When a part may claim it has passed a station: the definition of done, as one rule.

Part of arch.check. A component's status says which stations its work has passed (see engine.PASSED).
Raising a status is allowed only when no finding at the newly claimed stations is still open: no defect or
question, from any source, without an answer. Ideas never block.
"""

from __future__ import annotations

from arch.check.engine import PASSED, Finding, Kind, Report
from arch.model.graph import Graph
from arch.model.ids import ComponentId


def blockers(before: Graph, after: Graph, report: Report) -> tuple[Finding, ...]:
    """The open findings that stop the status changes from `before` to `after`."""
    claimed = {cid: PASSED[after[cid].status] - (PASSED[before[cid].status] if cid in before else frozenset())
               for cid in after.ids()}
    return tuple(f for f in report.findings
                 if f.kind is not Kind.IDEA and not report.is_answered(f)
                 and f.station in claimed.get(ComponentId(f.subject), frozenset()))


__all__ = ["blockers"]
