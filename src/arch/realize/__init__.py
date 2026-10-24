"""Relate the design to the artifacts that realize it (arch.realize).

The facade: pick an adapter per file and merge what each extracts. Pure: it sees a snapshot, never files.
"""

from __future__ import annotations

from collections.abc import Sequence

from arch.realize.facts import Adapter, Facts, Snapshot
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
    return Facts.merge(parts)


__all__ = ["extract"]
