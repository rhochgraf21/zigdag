"""The review deck: one topic per page, flipped with the arrow keys, verdicts saved as you go (arch.review.page).

Every page is rendered to HTML in Python (deterministic, testable); a small script shows one page at a
time, handles keys and posts verdicts to the local server. No external assets: it works offline.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import NewType

from arch.model.ids import Text
from arch.review.items import ReviewItem
from arch.review.page import style
from arch.review.page.render import page_html
from arch.review.session import Category, Decision, ItemState, Session, Weight
from arch.view.render import Count, JsonValue, Markdown

HtmlText = NewType("HtmlText", str)


def state(items: tuple[ReviewItem, ...], session: Session) -> JsonValue:
    """What the page needs to know about verdicts; also the server's API answer."""
    done, total = session.progress(items)
    return {
        "progress": {"done": done, "total": total},
        "items": [{"id": i.id, "digest": i.digest, "stage": i.stage.value, "title": i.title, "risk": i.risk.value,
                   "state": session.state(i, items).value, "verdict": _verdict(session, i),
                   "note": session.notes.get(i.id)} for i in items],
    }


def _verdict(session: Session, item: ReviewItem) -> JsonValue:
    v = session.verdicts.get(item.id)
    if v is None:
        return None
    return {"decision": v.decision.value, "comment": v.comment, "category": v.category.value, "weight": v.weight.value}


def render(items: tuple[ReviewItem, ...], session: Session, title: Text) -> HtmlText:
    pages = "\n".join(page_html(i, Count(n), Count(len(items)), session.notes.get(i.id)) for n, i in enumerate(items, 1))
    options = {"decisions": [d.value for d in Decision], "categories": [c.value for c in Category],
               "weights": [w.value for w in Weight], "states": [s.value for s in ItemState]}
    doc = style.TEMPLATE
    for key, value in (("{{TITLE}}", html.escape(title)), ("{{PAGES}}", pages),
                       ("{{STATE}}", json.dumps(state(items, session)).replace("</", "<\\/")),
                       ("{{OPTIONS}}", json.dumps(options)), ("{{CSS}}", style.CSS), ("{{JS}}", style.JS)):
        doc = doc.replace(key, value)
    return HtmlText(doc)


@dataclass(frozen=True)
class Board:
    """The review as the page shows it: pages and the verdicts given so far."""

    items: tuple[ReviewItem, ...]
    session: Session
    title: Text

    def to_html(self) -> HtmlText:
        return render(self.items, self.session, self.title)

    def to_json(self) -> JsonValue:
        return state(self.items, self.session)

    def to_markdown(self) -> Markdown:
        done, total = self.session.progress(self.items)
        return Markdown(f"{self.title}: {done} of {total} pages decided")


__all__ = ["Board", "HtmlText", "render", "state"]
