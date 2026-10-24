"""Relate the design to the artifacts that realize it (arch.realize).

The facade: pick an adapter per file and merge what each extracts. Pure: it sees a snapshot, never files.
"""

from __future__ import annotations

from collections.abc import Sequence

from dataclasses import replace

from arch.realize import evidence, history
from arch.realize.facts import Adapter, Effect, EffectUse, Facts, Reach, Snapshot, Text
from arch.realize.python import PythonAdapter

BUILT_IN: tuple[Adapter, ...] = (PythonAdapter(),)


def extract(snapshot: Snapshot, extra: Sequence[Adapter] = ()) -> Facts:
    """Facts for every file some adapter claims. Adapters given by the caller take precedence."""
    adapters = (*extra, *BUILT_IN)
    parts = []
    for path in sorted(snapshot.files):
        for adapter in adapters:
            if path.endswith(adapter.suffixes) and (unit := adapter.unit_name(path, snapshot.roots)) is not None:
                parts.append(adapter.extract(path, snapshot.files[path], unit, snapshot.roots.role_of(path)))
                break
    observed = Facts(
        changes=history.parse_log(snapshot.log) if snapshot.log else (),
        evidence=tuple(r for path in sorted(snapshot.reports) for r in evidence.parse_junit(path, snapshot.reports[path])),
    )
    return propagate_effects(Facts.merge([*parts, observed]))


def propagate_effects(facts: Facts) -> Facts:
    """Add transitive effects: a symbol has every effect of the project symbols it calls (fixed point).
    Calls that resolve to nothing in the project (stdlib, third parties) contribute nothing here; their
    known effects were already recorded as direct by the adapter."""
    key = lambda unit, symbol: f"{unit}.{symbol}"  # noqa: E731
    direct: dict[str, set[Effect]] = {}
    for e in facts.effects:
        direct.setdefault(key(e.unit, e.symbol), set()).add(e.effect)
    calls: dict[str, list] = {}
    for c in facts.calls:
        calls.setdefault(key(c.unit, c.symbol), []).append(c)
    defined = set(direct) | set(calls)
    aliases = {key(a.unit, a.name): a.target for a in facts.aliases}

    def targets(callee: str, depth: int = 0) -> list[str]:
        if callee in aliases and depth < 8:  # a re-exported name: follow it to where it is defined
            return targets(aliases[callee], depth + 1)
        return [t for t in (callee, f"{callee}.__init__", f"{callee}.__post_init__", f"{callee}.__call__") if t in defined]

    total = {k: set(v) for k, v in direct.items()}
    changed = True
    while changed:
        changed = False
        for k, cs in calls.items():
            have = total.setdefault(k, set())
            for c in cs:
                for t in targets(c.callee):
                    new = total.get(t, set()) - have
                    if new:
                        have |= new
                        changed = True

    added = []
    unit_of = {key(c.unit, c.symbol): (c.unit, c.symbol) for c in facts.calls}
    for k, effects in sorted(total.items()):
        for effect in sorted(effects - direct.get(k, set()), key=lambda e: e.value):
            via = next(c for c in calls[k] for t in targets(c.callee) if effect in total.get(t, ()))
            unit, symbol = unit_of[k]
            added.append(EffectUse(unit, symbol, effect, Reach.TRANSITIVE, via.location, Text(via.callee)))
    return replace(facts, effects=tuple(sorted((*facts.effects, *added), key=lambda e: (e.location.path, e.location.line, repr(e)))))


__all__ = ["extract"]
