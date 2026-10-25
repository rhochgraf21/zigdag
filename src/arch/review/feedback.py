"""What a review decided, told to the author and summarised for the commit. Realizes arch.review.feedback.

The verdicts themselves are kept by arch.review.session; this part only reads them.
"""

from __future__ import annotations

from dataclasses import dataclass

from arch.review.items import ReviewItem, Stage
from arch.review.session import ItemState, Session, Weight
from arch.view.render import JsonValue, Markdown


@dataclass(frozen=True)
class Feedback:
    """What the author must still do, item by item: the agent reads this."""

    session: Session
    items: tuple[ReviewItem, ...]

    def to_markdown(self) -> Markdown:
        requests = self.session.open_requests(self.items)
        done, total = self.session.progress(self.items)
        head = f"review of {self.session.name}: {done} of {total} items decided, {len(requests)} change requests open"
        if not requests:
            return Markdown(head + ("; everything approved" if self.session.approves(self.items) else ""))
        lines = [head, ""]
        for n, (item, v) in enumerate(sorted(requests, key=lambda r: (r[1].weight is Weight.NIT, list(Stage).index(r[0].stage))), 1):
            where = f" at {v.anchor.path}:{v.anchor.line}" if v.anchor else ""
            lines.append(f"{n}. [{v.weight.value}, {v.category.value}] {item.title}{where}")
            lines.append(f"   {v.comment or '(no comment)'}")
            lines.append(f"   item: {item.id}; made at the {v.category.station.value} station, so an earlier check missed it")
        lines += ["", "Address each, then run `arch review --serve` (or ask the reviewer) for a fresh look.",
                  "Each request escaped every earlier check. Record it with `arch raise defect <subject> \"<request>\" "
                  "--station <station above> --found-at review --as person --by <reviewer>`, and when it is fixed, answer "
                  "it with `arch respond fixed` and a `--countermeasure`: what changes upstream so it is caught there next "
                  "time."]
        return Markdown("\n".join(lines))

    def to_json(self) -> JsonValue:
        return [{"item": i.id, "title": i.title, "weight": v.weight.value, "category": v.category.value,
                 "station": v.category.station.value,
                 "comment": v.comment, "anchor": {"path": v.anchor.path, "line": v.anchor.line} if v.anchor else None}
                for i, v in self.session.open_requests(self.items)]


@dataclass(frozen=True)
class Record:
    """What the review concluded, for a commit message or pull-request description."""

    session: Session
    items: tuple[ReviewItem, ...]

    def to_markdown(self) -> Markdown:
        states = [self.session.state(i, self.items) for i in self.items]
        count = {s: states.count(s) for s in ItemState}
        reviewers = sorted({v.reviewer for v in self.session.verdicts.values() if v.reviewer})
        lines = [f"Reviewed with arch: {count[ItemState.APPROVED]} of {len(self.items)} items approved"
                 + (f", {count[ItemState.CHANGES_REQUESTED]} with changes requested" if count[ItemState.CHANGES_REQUESTED] else "")
                 + (f", {count[ItemState.STALE] + count[ItemState.UNREVIEWED]} not yet reviewed in their current form"
                    if count[ItemState.STALE] + count[ItemState.UNREVIEWED] else "") + "."]
        accepted = [(i, self.session.verdicts[i.id]) for i, s in zip(self.items, states)
                    if s is ItemState.APPROVED and self.session.verdicts[i.id].comment]
        lines += [f"- {i.title}: {v.comment}" for i, v in accepted]
        lines += [f"Reviewed-by: {r}" for r in reviewers]
        return Markdown("\n".join(lines))

    def to_json(self) -> JsonValue:
        return {"approved": self.session.approves(self.items),
                "items": {i.id: self.session.state(i, self.items).value for i in self.items}}


__all__ = ["Feedback", "Record"]
