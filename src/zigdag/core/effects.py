"""The effect vocabulary (DESIGN2 §3): deal's marker names, plus env, custom and resource effects."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import NewType

Effect = NewType("Effect", str)  # read, network, verus.run, shop.orders_db.write

IO = Effect("io")

# Each built-in effect, with the phrase archform uses for it in a sentence.
BUILT_IN: Mapping[Effect, str] = {
    Effect("global"): "changing global state",
    Effect("import"): "importing code while running",
    IO: "input or output",
    Effect("read"): "reading files",
    Effect("write"): "writing files",
    Effect("stdout"): "writing to standard output",
    Effect("stderr"): "writing to standard error",
    Effect("stdin"): "reading standard input",
    Effect("network"): "using the network",
    Effect("syscall"): "making system calls",
    Effect("random"): "using randomness",
    Effect("time"): "reading the clock",
    Effect("env"): "reading environment variables",
}

IO_GROUP: frozenset[Effect] = frozenset(
    Effect(e) for e in ("read", "write", "stdout", "stderr", "stdin", "network", "syscall")
)

RESOURCE_ACCESS = ("read", "write")  # a data container's own effects: <container>.read and <container>.write


def expand(effects: Iterable[Effect]) -> frozenset[Effect]:
    """The effects meant, with the io group replaced by its members."""
    out: set[Effect] = set()
    for e in effects:
        out |= IO_GROUP if e == IO else {e}
    return frozenset(out)


def resource_container(effect: Effect) -> str | None:
    """The container name in a resource effect such as shop.orders_db.write, or None."""
    head, dot, access = effect.rpartition(".")
    return head if dot and access in RESOURCE_ACCESS and "." in head else None


def phrase(effect: Effect) -> str:
    if effect in BUILT_IN:
        return BUILT_IN[effect]
    container = resource_container(effect)
    if container is not None:
        words = container.rpartition(".")[2].replace("_", " ")
        return f"reading the {words}" if effect.endswith(".read") else f"writing to the {words}"
    return f"the {effect} effect"
