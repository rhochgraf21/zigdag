"""Where each value in a TypeScript function comes from, for planned-effects (DESIGN2 §4.1), and what the function
does with each of its parameters, for narrow-parameters: the arguments of its calls and the conditions it branches
on, each traced back to constants, parameters and calls, and every comparison, arithmetic or logic it works out.
Tracing is by name inside the function, and ignores order, so a name bound twice comes from both. Which of these
are plan values is for the core to say: only it knows which functions are pure.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from tree_sitter import Node

from zigdag.adapters.typescript import apis
from zigdag.core.code import Computation, Need, Place, PlannedUse, Qualified, Source, Span, TypeOf, ValueSource
from zigdag.core.names import Identifier
from zigdag.core.texts import Written

ENCODING = "utf-8"
_CONSTANT = ValueSource(Source.CONSTANT)
_WORKED_OUT = ValueSource(Source.WORKED_OUT)
_UNKNOWN = ValueSource(Source.UNKNOWN)
_RAISED = ValueSource(Source.CALL)  # an error caught from a call: what some call threw
_UNTYPED = ValueSource(Source.PARAMETER)
_THIS = "this"
_LITERALS = frozenset({"string", "number", "true", "false", "null", "undefined", "regex", "arrow_function",
                       "function_expression", "generator_function"})
_WORKING = frozenset({"binary_expression", "ternary_expression"})  # expressions that work something out
_WORKING_OR_UNARY = _WORKING | {"unary_expression"}
_CHANGES_IN_PLACE = frozenset({"augmented_assignment_expression", "update_expression"})  # total += 1, count++
_SIGNS = frozenset({"-", "+"})  # what makes a number negative or positive as written, and works nothing out
_WRAPPERS = frozenset({"await_expression", "parenthesized_expression", "non_null_expression", "as_expression",
                       "satisfies_expression", "spread_element", "template_substitution"})  # a value, said another way
_FUNCTIONS = frozenset({"arrow_function", "function_expression", "generator_function", "function_declaration",
                        "generator_function_declaration", "method_definition"})
_PATTERNS = frozenset({"object_pattern", "array_pattern"})
_LOOPS_OVER = "for_in_statement"  # for (const x of xs), for (const k in o)
_CONDITIONED = frozenset({"if_statement", "while_statement", "do_statement", "for_statement"})
_SWITCH = "switch_statement"
_CALLS = frozenset({"call_expression", "new_expression"})
_AND_OR = frozenset({"&&", "||"})
_COMPARES = frozenset({"===", "==", "!==", "!="})
_NOT = "!"

Resolve = Callable[[Node | None], "Qualified | None"]
ValueType = Callable[[Node | None], "TypeOf | None"]
Spanned = Callable[[Node], Span]


def _text(node: Node | None) -> str:
    return node.text.decode(ENCODING) if node is not None and node.text is not None else ""


def inside(node: Node) -> Iterator[Node]:
    """Every node inside one, itself aside."""
    for child in node.named_children:
        yield child
        yield from inside(child)


def _unwrapped(node: Node) -> Node:
    while node.type == "parenthesized_expression" and node.named_children:
        node = node.named_children[0]
    return node


def _operator(node: Node) -> str:
    return _text(node.child_by_field_name("operator"))


def _names_in(pattern: Node) -> Iterator[str]:
    """Each name a pattern binds: the name itself, or every name a destructuring pattern takes out."""
    if pattern.type == "identifier" or pattern.type == "shorthand_property_identifier_pattern":
        yield _text(pattern)
    for child in pattern.named_children if pattern.type != "identifier" else ():
        if child.type == "pair_pattern":
            yield from _names_in(child.child_by_field_name("value") or child)
        elif child.type not in ("property_identifier", "type_annotation"):
            yield from _names_in(child)


@dataclass(frozen=True)
class Traced:
    planned_uses: tuple[PlannedUse, ...]
    computations: tuple[Computation, ...]


@dataclass(frozen=True)
class ParameterUse:
    """What a function's body does with one of its parameters."""

    branched_on: bool
    fields_read: tuple[Identifier, ...]
    used_whole: bool


def _sum(groups: Iterator[tuple[ValueSource, ...]]) -> tuple[ValueSource, ...]:
    """The sources of a value made of several: each source once, in the order first seen."""
    return tuple(dict.fromkeys(s for g in groups for s in g)) or (_CONSTANT,)


class _Function:
    """One function's body, with every name bound in it, ready to trace values back to where they come from."""

    def __init__(self, body: Node, parameters: Mapping[Identifier, Qualified | None], place: Place, owner: Qualified | None,
                 resolve: Resolve, value_type: ValueType, span: Spanned) -> None:
        self.body = body
        self.place = place
        self.resolve = resolve
        self.value_type = value_type
        self.span = span
        self.params: dict[str, ValueSource] = {name: ValueSource(Source.PARAMETER, named)
                                               for name, named in parameters.items()}
        if owner is not None:
            self.params[_THIS] = ValueSource(Source.PARAMETER, owner)  # the object a method is called on
        self.bound: dict[str, list[Node | ValueSource]] = {}
        self.busy: set[str] = set()
        for node in inside(body):
            self._binds(node)

    # ---- names ---------------------------------------------------------------------------------------------------

    def _bind(self, target: Node | None, value: Node | ValueSource | None) -> None:
        for name in _names_in(target) if target is not None else ():
            self.bound.setdefault(name, []).append(value if value is not None else _UNKNOWN)

    def _binds(self, node: Node) -> None:
        """The names a node binds, and what each is bound to."""
        kind = node.type
        if kind == "variable_declarator":
            self._bind(node.child_by_field_name("name"), node.child_by_field_name("value"))
        elif kind == "assignment_expression":
            self._bind(node.child_by_field_name("left"), node.child_by_field_name("right"))
        elif kind == "augmented_assignment_expression":
            self._bind(node.child_by_field_name("left"), _WORKED_OUT)
        elif kind == "update_expression":
            self._bind(node.child_by_field_name("argument"), _WORKED_OUT)
        elif kind == _LOOPS_OVER:
            self._bind(node.child_by_field_name("left"), node.child_by_field_name("right"))
        elif kind == "catch_clause":
            self._bind(node.child_by_field_name("parameter"), _RAISED)
        elif kind in ("function_declaration", "generator_function_declaration", "class_declaration"):
            self._bind(node.child_by_field_name("name"), _CONSTANT)
        if kind in _FUNCTIONS:  # an inner function's parameters, given by whatever calls it
            parameters = node.child_by_field_name("parameters") or node.child_by_field_name("parameter")
            for parameter in (parameters.named_children or [parameters]) if parameters is not None else ():
                self._bind(parameter.child_by_field_name("pattern") or parameter, _UNTYPED)

    def _local(self, name: str) -> bool:
        return name in self.params or name in self.bound

    # ---- sources -------------------------------------------------------------------------------------------------

    def _name(self, name: str, node: Node) -> tuple[ValueSource, ...]:
        if name in self.busy:
            return ()
        if not self._local(name):
            return (_CONSTANT,) if self.resolve(node) is not None else (_UNKNOWN,)
        self.busy.add(name)
        try:
            found: list[tuple[ValueSource, ...]] = [(self.params[name],)] if name in self.params else []
            found += [(v,) if isinstance(v, ValueSource) else self.sources(v) for v in self.bound.get(name, ())]
            return tuple(dict.fromkeys(s for g in found for s in g))
        finally:
            self.busy.discard(name)

    @staticmethod
    def _root(node: Node) -> Node:
        while node.type in ("member_expression", "subscript_expression"):
            node = node.child_by_field_name("object") or node
        return node

    def _arguments(self, node: Node) -> list[Node]:
        arguments = node.child_by_field_name("arguments")
        return list(arguments.named_children) if arguments is not None else []

    def call(self, node: Node) -> ValueSource:
        """What a call returns, as a source: who is called, on what, and with what."""
        made_from = _sum(self.sources(a) for a in self._arguments(node))
        function = node.child_by_field_name("function") or node.child_by_field_name("constructor")
        if function is None:
            return ValueSource(Source.CALL, built_from=made_from)
        root = self._root(function)
        local = root.type == "identifier" and self._local(_text(root))
        name = None if local else self.resolve(function)
        if name in apis.BUILDERS:
            return ValueSource(Source.BUILT, built_from=made_from)
        member = function.type == "member_expression"
        receiver = self.value_type(function.child_by_field_name("object")) if member and name is None else None
        method = Identifier(_text(function.child_by_field_name("property"))) if member else None
        return ValueSource(Source.CALL, name, receiver, method, made_from)

    def sources(self, node: Node | None) -> tuple[ValueSource, ...]:
        """Where a value comes from: every constant, parameter and call it is read, iterated or built from."""
        if node is None:
            return (_UNKNOWN,)
        kind = node.type
        if kind in _LITERALS:
            return (_CONSTANT,)
        if kind == "unary_expression" and _operator(node) in _SIGNS and all(
                c.type == "number" for c in node.named_children):
            return (_CONSTANT,)  # a negative number, as written
        if kind in _WORKING_OR_UNARY:
            return (_WORKED_OUT,)
        if kind == "identifier":
            return self._name(_text(node), node)
        if kind == _THIS:
            return self._name(_THIS, node)
        if kind == "member_expression":
            root = self._root(node)
            if root.type == "identifier" and not self._local(_text(root)) and self.resolve(node) is not None:
                return (_CONSTANT,)  # a name declared at the top of a module, or that is there without being imported
            return self.sources(node.child_by_field_name("object"))
        if kind == "subscript_expression":
            return _sum(iter((self.sources(node.child_by_field_name("object")),
                              self.sources(node.child_by_field_name("index")))))
        if kind in _CALLS:
            return (self.call(node),)
        if kind in _WRAPPERS:
            return self.sources(next(iter(node.named_children), None))
        if kind in ("template_string", "array"):
            return _sum(self.sources(part) for part in node.named_children
                        if part.type not in ("string_fragment", "escape_sequence"))
        if kind == "object":
            return _sum(self.sources(pair.child_by_field_name("value") or pair) for pair in node.named_children)
        if kind == "shorthand_property_identifier":
            return self._name(_text(node), node)
        return (_UNKNOWN,)

    # ---- what must be planned ------------------------------------------------------------------------------------

    def _use(self, need: Need, value: Node, call: ValueSource | None = None) -> PlannedUse:
        return PlannedUse(self.place, need, Written(_text(value)), self.sources(value), self.span(value), call)

    def uses(self) -> Iterator[PlannedUse]:
        for node in inside(self.body):
            if node.type in _CALLS:
                call = self.call(node)
                for value in self._arguments(node):
                    yield self._use(Need.ARGUMENT, value, call)
            elif (decided_by := _decided_by(node)) is not None:
                yield self._use(Need.CONDITION, _unwrapped(decided_by))

    def computations(self) -> Iterator[Computation]:
        for node in inside(self.body):
            worked_out = node.type in _WORKING | _CHANGES_IN_PLACE or (
                node.type == "unary_expression" and self.sources(node) == (_WORKED_OUT,))
            outer = _unwrapped_parent(node)
            if worked_out and (outer is None or outer.type not in _WORKING_OR_UNARY):  # the outermost one only
                yield Computation(self.place, Written(_text(node)), self.span(node))


def _decided_by(node: Node) -> Node | None:
    """What a statement that branches or loops decides by: an if's or a loop's condition, or what a switch is on;
    None for any other node."""
    if node.type in _CONDITIONED:
        return node.child_by_field_name("condition")
    return node.child_by_field_name("value") if node.type == _SWITCH else None


def _unwrapped_parent(node: Node) -> Node | None:
    """What an expression is part of, the brackets around it not counting."""
    parent = node.parent
    while parent is not None and parent.type == "parenthesized_expression":
        parent = parent.parent
    return parent


def trace(body: Node, parameters: Mapping[Identifier, Qualified | None], place: Place, owner: Qualified | None,
          resolve: Resolve, value_type: ValueType, span: Spanned) -> Traced:
    """A function's values that must be plan values unless it is pure, and what it works out."""
    function = _Function(body, parameters, place, owner, resolve, value_type, span)
    return Traced(tuple(function.uses()), tuple(function.computations()))


def _tested(test: Node) -> set[str]:
    """The names a branch picks by: flag, !flag, kind === "x", kind === Kind.A, and either side of && and ||."""
    test = _unwrapped(test)
    if test.type == "identifier":
        return {_text(test)}
    if test.type == "unary_expression" and _operator(test) == _NOT:
        return _tested(test.child_by_field_name("argument") or test)
    if test.type == "binary_expression":
        left, right = test.child_by_field_name("left"), test.child_by_field_name("right")
        if left is None or right is None:
            return set()
        if _operator(test) in _AND_OR:
            return _tested(left) | _tested(right)
        sides = (_unwrapped(left), _unwrapped(right))
        names = [_text(s) for s in sides if s.type == "identifier"]
        fixed = [s for s in sides if s.type in _LITERALS or s.type == "member_expression"]
        return set(names) if _operator(test) in _COMPARES and len(names) == 1 and fixed else set()
    return set()


def _branch_tests(body: Node) -> Iterator[Node]:
    """What the body takes branches by: the conditions of if, while and conditional expressions, and what a switch
    is on."""
    for node in inside(body):
        decided_by = node.child_by_field_name("condition") if node.type == "ternary_expression" else _decided_by(node)
        if decided_by is not None:
            yield decided_by


def parameter_uses(body: Node, names: Sequence[str]) -> dict[str, ParameterUse]:
    """For each parameter: whether the body branches on it, the fields of it the body reads, and whether the body
    also uses it whole. Reading a field is `p.total`; calling `p.total()` uses p whole, as passing p on does."""
    reads: dict[str, list[Identifier]] = {name: [] for name in names}
    whole: set[str] = set()
    for node in inside(body):
        if node.type != "identifier" or _text(node) not in reads:
            continue
        holder = node.parent
        of_member = holder is not None and holder.type == "member_expression" and \
            holder.child_by_field_name("object") == node
        outer = holder.parent if of_member and holder is not None else None
        called = outer is not None and outer.type in _CALLS and outer.child_by_field_name("function") == holder
        written = outer is not None and outer.type in ("assignment_expression", "augmented_assignment_expression") \
            and outer.child_by_field_name("left") == holder
        if of_member and holder is not None and not called and not written:
            field = Identifier(_text(holder.child_by_field_name("property")))
            if field not in reads[_text(node)]:
                reads[_text(node)].append(field)
        else:
            whole.add(_text(node))
    tested = {name for test in _branch_tests(body) for name in _tested(test)}
    return {name: ParameterUse(name in tested, tuple(reads[name]), name in whole) for name in names}
