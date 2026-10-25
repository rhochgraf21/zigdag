"""Verdicts on review items: what was decided, what changed since, and what the author must still do.

Realizes arch.review.session. A verdict is recorded against an item's digest; when the item changes, the
verdict goes stale and the item needs a fresh look. Nothing else does. Change requests carry a category
and a weight, so the author (usually an agent) can act on each one precisely.
"""

from __future__ import annotations

import enum
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import NewType

from arch.check.engine import Station
from arch.model.ids import Text
from arch.review.items import Digest, ItemId, ReviewItem
from arch.view.render import Count, JsonValue

SessionText = NewType("SessionText", str)  # the stored form of a session (JSON)
Reviewer = NewType("Reviewer", str)
FORMAT = 1


class Decision(enum.Enum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes requested"
    COMMENTED = "commented"


class Category(enum.Enum):
    INTENT = "intent"  # the wrong problem, or a solution posing as a need
    DESIGN = "design"  # a better approach exists, or a decision is unrecorded
    BUG = "bug"
    TEST = "test"  # missing, weak or wrong evidence
    NAMING = "naming"
    OTHER = "other"

    @property
    def station(self) -> Station:
        """Where a defect of this category is made, so where an earlier check could have caught it."""
        return {Category.INTENT: Station.REQUIREMENTS, Category.DESIGN: Station.SOLUTION, Category.BUG: Station.CODE,
                Category.TEST: Station.EVIDENCE, Category.NAMING: Station.INTERFACE}.get(self, Station.REVIEW)


class Weight(enum.Enum):
    BLOCKING = "blocking"
    NIT = "nit"  # worth doing, not worth waiting for


class ItemState(enum.Enum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes requested"
    COMMENTED = "commented"
    STALE = "changed since your verdict"
    BLOCKED = "waiting on a change to an earlier page"


@dataclass(frozen=True)
class Anchor:
    path: Text
    line: Count


@dataclass(frozen=True)
class Verdict:
    item: ItemId
    decision: Decision
    digest: Digest  # what the item showed when the verdict was given
    reviewer: Reviewer
    comment: Text | None = None
    category: Category = Category.OTHER
    weight: Weight = Weight.BLOCKING
    anchor: Anchor | None = None


@dataclass(frozen=True)
class Session:
    name: Text  # usually the branch under review
    verdicts: Mapping[ItemId, Verdict] = field(default_factory=dict)
    notes: Mapping[ItemId, Text] = field(default_factory=dict)  # the author's notes, item by item

    def decide(self, verdict: Verdict) -> Session:
        return replace(self, verdicts={**self.verdicts, verdict.item: verdict})

    def note(self, item: ItemId, text: Text) -> Session:
        return replace(self, notes={**self.notes, item: text})

    def state(self, item: ReviewItem, items: Iterable[ReviewItem] = ()) -> ItemState:
        v = self.verdicts.get(item.id)
        if v is not None and v.digest != item.digest:
            return ItemState.STALE
        by_id = {i.id: i for i in items}
        for blocker in item.blocked_by:
            upstream = by_id.get(blocker)
            uv = self.verdicts.get(blocker)
            if upstream is not None and uv is not None and uv.decision is Decision.CHANGES_REQUESTED and uv.digest == upstream.digest:
                return ItemState.BLOCKED
        if v is None:
            return ItemState.UNREVIEWED
        return {Decision.APPROVED: ItemState.APPROVED, Decision.CHANGES_REQUESTED: ItemState.CHANGES_REQUESTED,
                Decision.COMMENTED: ItemState.COMMENTED}[v.decision]

    def open_requests(self, items: Iterable[ReviewItem]) -> tuple[tuple[ReviewItem, Verdict], ...]:
        """Change requests whose item has not changed since: still the author's to do, blocked upstream or not."""
        return tuple((i, v) for i in items if (v := self.verdicts.get(i.id)) is not None
                     and v.decision is Decision.CHANGES_REQUESTED and v.digest == i.digest)

    def progress(self, items: Iterable[ReviewItem]) -> tuple[Count, Count]:
        """(items with a current verdict, all items)."""
        items = tuple(items)
        done = sum(1 for i in items if self.state(i, items) in (ItemState.APPROVED, ItemState.CHANGES_REQUESTED,
                                                                 ItemState.COMMENTED))
        return Count(done), Count(len(items))

    def approves(self, items: Iterable[ReviewItem]) -> bool:
        items = tuple(items)
        return bool(items) and all(self.state(i, items) is ItemState.APPROVED for i in items)

    # storage: plain JSON, versioned, so it can be kept, inspected, or committed later

    def dump(self) -> SessionText:
        def verdict(v: Verdict) -> JsonValue:
            return {"decision": v.decision.value, "digest": v.digest, "reviewer": v.reviewer, "comment": v.comment,
                    "category": v.category.value, "weight": v.weight.value,
                    "anchor": {"path": v.anchor.path, "line": v.anchor.line} if v.anchor else None}
        data = {"format": FORMAT, "name": self.name,
                "verdicts": {k: verdict(v) for k, v in sorted(self.verdicts.items())},
                "notes": dict(sorted(self.notes.items()))}
        return SessionText(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    @staticmethod
    def load(text: SessionText, name: Text) -> Session:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return Session(name)
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            return Session(name)
        verdicts = {}
        for item, v in (data.get("verdicts") or {}).items():
            try:
                anchor = Anchor(Text(v["anchor"]["path"]), Count(int(v["anchor"]["line"]))) if v.get("anchor") else None
                verdicts[ItemId(item)] = Verdict(ItemId(item), Decision(v["decision"]), Digest(v["digest"]),
                                                 Reviewer(v.get("reviewer", "")), v.get("comment"),
                                                 Category(v.get("category", "other")), Weight(v.get("weight", "blocking")),
                                                 anchor)
            except (KeyError, ValueError, TypeError):
                continue  # one unreadable verdict must not lose the rest
        notes = {ItemId(k): Text(v) for k, v in (data.get("notes") or {}).items() if isinstance(v, str)}
        return Session(Text(data.get("name") or name), verdicts, notes)


__all__ = ["Anchor", "Category", "Decision", "ItemState", "Reviewer", "Session", "SessionText",
           "Verdict", "Weight"]
