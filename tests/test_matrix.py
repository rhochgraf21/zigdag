from __future__ import annotations

import itertools

from hypothesis import given
from hypothesis import strategies as st

from arch import realizes
from arch.model.matrix import Coupling, layer

nodes = st.lists(st.sampled_from("abcdefghij"), min_size=1, max_size=10, unique=True)


@st.composite
def digraphs(draw, acyclic: bool):
    ns = sorted(draw(nodes))
    pairs = [(a, b) for a, b in itertools.permutations(ns, 2) if not acyclic or a > b]
    edges = draw(st.sets(st.sampled_from(pairs))) if pairs else set()
    return ns, {n: sorted(b for a, b in edges if a == n) for n in ns}


def reachable(deps, a, b):
    seen, todo = set(), [a]
    while todo:
        for d in deps[todo.pop()]:
            if d == b:
                return True
            if d not in seen:
                seen.add(d)
                todo.append(d)
    return False


@realizes("arch.model.matrix#AC4")
@given(digraphs(acyclic=True))
def test_each_layer_uses_only_earlier_layers(g):
    ns, deps = g
    result = layer(ns, deps.__getitem__)
    depth = {n: i for i, l in enumerate(result.layers) for n in l}
    assert all(depth[d] < depth[n] for n in ns for d in deps[n])
    assert not result.coupled


@realizes("arch.model.matrix#AC1", "arch.model.matrix#AC2")
@given(digraphs(acyclic=False))
def test_coupled_sets_are_exactly_the_cycles(g):
    ns, deps = g
    result = layer(ns, deps.__getitem__)
    together = {(a, b) for scc in result.coupled for a in scc for b in scc if a != b}
    mutual = {(a, b) for a in ns for b in ns if a != b and reachable(deps, a, b) and reachable(deps, b, a)}
    assert together == mutual


@realizes("arch.model.matrix#AC3")
@given(digraphs(acyclic=False), st.randoms())
def test_layering_ignores_input_order(g, rnd):
    ns, deps = g
    shuffled = list(ns)
    rnd.shuffle(shuffled)
    assert layer(ns, deps.__getitem__) == layer(shuffled, deps.__getitem__)


def test_matrix_classification():
    from tests.conftest import NEED, component, graph
    from arch.model.matrix import matrix_of

    base = {"needs/n.md": NEED, "components/s.md": component(serves="n")}
    uncoupled = graph({**base, "components/s/a.md": component(), "components/s/b.md": component()})
    decoupled = graph({**base, "components/s/a.md": component(uses="b"), "components/s/b.md": component()})
    coupled = graph({**base, "components/s/a.md": component(uses="b"), "components/s/b.md": component(uses="a")})
    assert matrix_of(uncoupled, "s").coupling is Coupling.UNCOUPLED
    assert matrix_of(decoupled, "s").coupling is Coupling.DECOUPLED
    assert matrix_of(decoupled, "s").order == ("s.b", "s.a")
    assert matrix_of(coupled, "s").coupling is Coupling.COUPLED
