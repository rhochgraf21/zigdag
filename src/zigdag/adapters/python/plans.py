"""Where each value in a Python function comes from, for planned-effects (DESIGN2 §4.1): the arguments of its calls
and the conditions it branches on, each traced back to constants, parameters and calls, and every comparison,
arithmetic or logic it works out. Tracing is by name inside the function, and ignores order, so a name bound twice
comes from both. Which of these are plan values is for the core to say: only it knows which functions are pure.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass

from zigdag.adapters.python import apis
from zigdag.core.code import Computation, Need, Place, PlannedUse, Qualified, Source, ValueSource

_CONSTANT = ValueSource(Source.CONSTANT)
_WORKED_OUT = ValueSource(Source.WORKED_OUT)
_UNKNOWN = ValueSource(Source.UNKNOWN)
_RAISED = ValueSource(Source.CALL)  # an error caught from a call: what some call raised
_UNTYPED = ValueSource(Source.PARAMETER)
_WORKING = (ast.BinOp, ast.Compare, ast.BoolOp, ast.IfExp)  # expressions that work something out
_WORKING_OR_UNARY = (*_WORKING, ast.UnaryOp)
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


@dataclass(frozen=True)
class Traced:
    planned_uses: tuple[PlannedUse, ...]
    computations: tuple[Computation, ...]


def _sum(groups: Iterator[tuple[ValueSource, ...]]) -> tuple[ValueSource, ...]:
    """The sources of a value made of several: each source once, in the order first seen."""
    return tuple(dict.fromkeys(s for g in groups for s in g)) or (_CONSTANT,)


class _Function:
    """One function's body, with every name bound in it, ready to trace values back to where they come from."""

    def __init__(self, scanner, node: ast.FunctionDef | ast.AsyncFunctionDef, place: Place, owner: Qualified | None):  # noqa: ANN001 (the Scanner)
        self.scanner = scanner
        self.node = node
        self.place = place
        self.params: dict[str, ValueSource] = {}
        self.bound: dict[str, list[ast.expr | ValueSource]] = {}
        self.busy: set[str] = set()
        self._parameters(node, owner)
        for inner in self._walk():
            self._binds(inner)

    def _walk(self) -> Iterator[ast.AST]:
        return (n for stmt in self.node.body for n in ast.walk(stmt))

    # ---- names ---------------------------------------------------------------------------------------------------

    def _parameters(self, node: ast.FunctionDef | ast.AsyncFunctionDef, owner: Qualified | None) -> None:
        a = node.args
        params = [*a.posonlyargs, *a.args, *a.kwonlyargs]
        for i, p in enumerate(params):
            named = self.scanner.type_expr(p.annotation).named if p.annotation is not None else None
            if named is None and i == 0 and owner is not None and p.arg in apis.RECEIVERS:
                named = owner  # self, or cls: its type is the class the method is on
            self.params[p.arg] = ValueSource(Source.PARAMETER, Qualified(named) if named else None)
        for p in (a.vararg, a.kwarg):
            if p is not None:
                self.params[p.arg] = _UNTYPED

    def _bind(self, target: ast.expr, value: ast.expr | ValueSource) -> None:
        if isinstance(target, ast.Name):
            self.bound.setdefault(target.id, []).append(value)
        elif isinstance(target, ast.Tuple | ast.List):
            for element in target.elts:
                self._bind(element, value)
        elif isinstance(target, ast.Starred):
            self._bind(target.value, value)

    def _binds(self, node: ast.AST) -> None:
        """The names a node binds, and what each is bound to."""
        if isinstance(node, ast.Assign):
            for target in node.targets:
                self._bind(target, node.value)
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr) and node.value is not None:
            self._bind(node.target, node.value)
        elif isinstance(node, ast.AugAssign):
            self._bind(node.target, _WORKED_OUT)
        elif isinstance(node, ast.For | ast.AsyncFor | ast.comprehension):
            self._bind(node.target, node.iter)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            self._bind(node.optional_vars, node.context_expr)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            self.bound.setdefault(node.name, []).append(_RAISED)
        elif isinstance(node, ast.MatchAs | ast.MatchStar) and node.name:
            self.bound.setdefault(node.name, []).append(_UNKNOWN)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            self.bound.setdefault(node.name, []).append(_CONSTANT)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                self.bound.setdefault((alias.asname or alias.name).split(".")[0], []).append(_CONSTANT)
        if isinstance(node, _FUNCTIONS):  # an inner function's parameters, given by whatever calls it
            for p in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg,
                      node.args.kwarg]:
                if p is not None:
                    self.bound.setdefault(p.arg, []).append(_UNTYPED)

    def _local(self, name: str) -> bool:
        return name in self.params or name in self.bound

    # ---- sources -------------------------------------------------------------------------------------------------

    def _name(self, node: ast.Name) -> tuple[ValueSource, ...]:
        if node.id in self.busy:
            return ()
        if not self._local(node.id):
            known = self.scanner.resolve(node) is not None or node.id in apis.MODULE_NAMES
            return (_CONSTANT,) if known else (_UNKNOWN,)
        self.busy.add(node.id)
        try:
            found = [(self.params[node.id],)] if node.id in self.params else []
            found += [(v,) if isinstance(v, ValueSource) else self.sources(v) for v in self.bound.get(node.id, ())]
            return tuple(dict.fromkeys(s for g in found for s in g))
        finally:
            self.busy.discard(node.id)

    def _root(self, node: ast.expr) -> ast.expr:
        while isinstance(node, ast.Attribute | ast.Subscript):
            node = node.value
        return node

    def call(self, node: ast.Call) -> ValueSource:
        """What a call returns, as a source: who is called, on what, and with what."""
        made_from = _sum(self.sources(a) for a in [*node.args, *(k.value for k in node.keywords)])
        func = node.func
        root = self._root(func)
        local = isinstance(root, ast.Name) and self._local(root.id) and root.id not in apis.RECEIVERS
        name = None if local else self.scanner.resolve(func)
        if name in apis.BUILDERS:
            return ValueSource(Source.BUILT, built_from=made_from)
        receiver = self.scanner.value_type(func.value) if isinstance(func, ast.Attribute) and name is None else None
        method = func.attr if isinstance(func, ast.Attribute) else None
        return ValueSource(Source.CALL, Qualified(name) if name else None, receiver, method, made_from)

    def sources(self, node: ast.expr) -> tuple[ValueSource, ...]:
        """Where a value comes from: every constant, parameter and call it is read, iterated or built from."""
        if isinstance(node, ast.Constant | ast.Lambda):
            return (_CONSTANT,)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd) and isinstance(
                node.operand, ast.Constant):
            return (_CONSTANT,)  # a negative number, as written
        if isinstance(node, _WORKING_OR_UNARY):
            return (_WORKED_OUT,)
        if isinstance(node, ast.Name):
            return self._name(node)
        if isinstance(node, ast.Attribute):
            root = self._root(node)
            if isinstance(root, ast.Name) and not self._local(root.id) and self.scanner.resolve(node) is not None:
                return (_CONSTANT,)  # a name defined at the top of a module: apis.READ, Kind.FOOT
            return self.sources(node.value)
        if isinstance(node, ast.Subscript):
            return _sum(iter((self.sources(node.value), self.sources(node.slice))))
        if isinstance(node, ast.Call):
            return (self.call(node),)
        if isinstance(node, ast.Starred | ast.Await | ast.NamedExpr | ast.FormattedValue):
            return self.sources(node.value)
        if isinstance(node, ast.JoinedStr):
            return _sum(self.sources(v) for v in node.values)
        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            return _sum(self.sources(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return _sum(self.sources(e) for e in [*(k for k in node.keys if k is not None), *node.values])
        if isinstance(node, ast.Slice):
            return _sum(self.sources(e) for e in (node.lower, node.upper, node.step) if e is not None)
        if isinstance(node, ast.ListComp | ast.SetComp | ast.GeneratorExp):
            return self.sources(node.elt)
        if isinstance(node, ast.DictComp):
            return _sum(iter((self.sources(node.key), self.sources(node.value))))
        return (_UNKNOWN,)

    # ---- what must be planned ------------------------------------------------------------------------------------

    def _use(self, need: Need, value: ast.expr, call: ValueSource | None = None) -> PlannedUse:
        return PlannedUse(self.place, need, ast.unparse(value), self.sources(value), self.scanner.span(value), call)

    def uses(self) -> Iterator[PlannedUse]:
        for node in self._walk():
            if isinstance(node, ast.Call):
                call = self.call(node)
                for value in [*node.args, *(k.value for k in node.keywords)]:
                    yield self._use(Need.ARGUMENT, value, call)
            elif isinstance(node, ast.If | ast.While | ast.Assert):
                yield self._use(Need.CONDITION, node.test)
            elif isinstance(node, ast.Match):
                yield self._use(Need.CONDITION, node.subject)

    def computations(self) -> Iterator[Computation]:
        parents = {child: parent for parent in self._walk() for child in ast.iter_child_nodes(parent)}
        for node in self._walk():
            worked_out = isinstance(node, (*_WORKING, ast.AugAssign)) or (
                isinstance(node, ast.UnaryOp) and self.sources(node) == (_WORKED_OUT,))
            if worked_out and not isinstance(parents.get(node), _WORKING_OR_UNARY):  # the outermost one only
                yield Computation(self.place, ast.unparse(node), self.scanner.span(node))
            elif isinstance(node, ast.comprehension):
                for test in node.ifs:  # a filter decides, whatever it tests
                    if not isinstance(test, _WORKING_OR_UNARY):
                        yield Computation(self.place, f"if {ast.unparse(test)}", self.scanner.span(test))


def trace(scanner, node: ast.FunctionDef | ast.AsyncFunctionDef, place: Place, owner: Qualified | None) -> Traced:  # noqa: ANN001 (the Scanner)
    """A function's values that must be plan values unless it is pure, and what it works out."""
    function = _Function(scanner, node, place, owner)
    return Traced(tuple(function.uses()), tuple(function.computations()))
