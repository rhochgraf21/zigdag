"""Structures written as zod schemas (DESIGN2 §5.2): a project that uses zod says what its data is made of there,
and takes its types from the schemas.

    export const Order = z.object({ id: z.string(), lines: z.array(Line) });
    export type Order = z.infer<typeof Order>;

The schema is the structure: its keys are the fields, and what each is given says the field's type. The type taken
from it has the same name and is the same structure, so it is not read as one of its own.

A schema is read where it is written out: an object's shape, an enumeration's values, and what a schema extends.
One worked out from another, by picking or leaving out or merging, is not followed: it is left a constant.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tree_sitter import Node

from zigdag.adapters.typescript import apis
from zigdag.core.code import Qualified, TypeExpr, TypeKind
from zigdag.core.names import Identifier
from zigdag.core.texts import Say, Written

ENCODING = "utf-8"
PACKAGE = "zod"
_NAMESPACE = "z"  # how zod's functions are usually reached: z.object(...)
_OBJECT, _ENUM, _EXTEND = "object", "enum", "extend"
_STRICT_OBJECTS = frozenset({"strictObject", "looseObject"})  # an object, said with how unknown keys are taken
_DESCRIBE = "describe"  # the method that gives a schema its description
# What a schema of a plain value is, in the language's own types.
_PLAIN = {"string": "string", "number": "number", "int": "number", "bigint": "bigint", "date": "Date",
          "symbol": "symbol", "email": "string", "uuid": "string", "url": "string", "iso": "string"}
_WRAPPING = frozenset({"array", "record", "map", "set", "tuple", "promise", "readonly"})  # around other schemas
_NOTHING = frozenset({"null", "undefined", "void", "never"})
_ANYTHING = frozenset({"any", "unknown", "custom"})
_MAY_BE_NOTHING = frozenset({"optional", "nullable", "nullish"})  # methods that let a value be absent
_CHOICES = frozenset({"union", "discriminatedUnion"})
_LITERAL, _LAZY = "literal", "lazy"

Resolve = Callable[[Node | None], "Qualified | None"]


def _text(node: Node | None) -> str:
    return node.text.decode(ENCODING) if node is not None and node.text is not None else ""


def _plain_text(node: Node | None) -> str | None:
    """What a string written as a plain constant says."""
    if node is None or node.type != "string":
        return None
    return "".join(_text(part) for part in node.named_children if part.type == "string_fragment")


@dataclass(frozen=True)
class SchemaField:
    name: Identifier
    type: TypeExpr | None
    description: Say | None
    node: Node  # where it is written


@dataclass(frozen=True)
class Schema:
    """A structure written as a zod schema: an object with its fields, or an enumeration with its values."""

    fields: tuple[SchemaField, ...] = ()
    members: tuple[Identifier, ...] = ()
    base: Qualified | None = None  # the schema it extends


@dataclass(frozen=True)
class _Reader:
    resolve: Resolve

    def _zod(self, node: Node | None) -> str | None:
        """Which of zod's functions a callee is: object for z.object, zod.object or an imported object."""
        named = self.resolve(node)
        if named is None or not named.startswith(f"{PACKAGE}."):
            return None
        return named.removeprefix(f"{PACKAGE}.").removeprefix(f"{_NAMESPACE}.")

    @staticmethod
    def _arguments(call: Node) -> list[Node]:
        arguments = call.child_by_field_name("arguments")
        return list(arguments.named_children) if arguments is not None else []

    def _described(self, call: Node) -> Say | None:
        """What a chain of calls says of its schema with .describe("...")."""
        function = call.child_by_field_name("function")
        while call.type == "call_expression" and function is not None and function.type == "member_expression":
            if _text(function.child_by_field_name("property")) == _DESCRIBE:
                said = _plain_text(next(iter(self._arguments(call)), None))
                return Say(said) if said else None
            inner = function.child_by_field_name("object")
            if inner is None or inner.type != "call_expression":
                return None
            call, function = inner, inner.child_by_field_name("function")
        return None

    def type_of(self, node: Node | None) -> TypeExpr | None:
        """The type a schema stands for, as written: what a field of a structure holds."""
        if node is None:
            return None
        text = Written(_text(node))
        if node.type in ("identifier", "member_expression") and self._zod(node) is None:
            named = self.resolve(node)  # another schema, by its name
            return TypeExpr(TypeKind.REF, text, named or Qualified(text))
        if node.type != "call_expression":
            return TypeExpr(TypeKind.UNKNOWN, text)
        function, arguments = node.child_by_field_name("function"), self._arguments(node)
        made_by = self._zod(function)
        if made_by is not None:
            return self._made(made_by, arguments, text)
        if function is not None and function.type == "member_expression":  # a method on a schema: .min(1), .optional()
            inner = self.type_of(function.child_by_field_name("object"))
            if _text(function.child_by_field_name("property")) in _MAY_BE_NOTHING and inner is not None:
                return TypeExpr(TypeKind.UNION, text, args=(inner, TypeExpr(TypeKind.NONE, text)))
            return inner  # a method that narrows or names a schema leaves its type what it was
        return TypeExpr(TypeKind.UNKNOWN, text)

    def _made(self, made_by: str, arguments: list[Node], text: Written) -> TypeExpr:
        first = arguments[0] if arguments else None
        if made_by in _PLAIN:
            return TypeExpr(TypeKind.REF, text, Qualified(f"{apis.BUILTINS_PREFIX}{_PLAIN[made_by]}"))
        if made_by == apis.TRUTH:
            return TypeExpr(TypeKind.BOOL, text)
        if made_by in _NOTHING:
            return TypeExpr(TypeKind.NONE, text)
        if made_by in _ANYTHING:
            return TypeExpr(TypeKind.ANY, text)
        if made_by in _WRAPPING:
            return TypeExpr(TypeKind.CONTAINER, text, args=tuple(t for a in arguments if (t := self.type_of(a))))
        if made_by == _ENUM or made_by == _LITERAL:
            return TypeExpr(TypeKind.LITERAL, text, values=_values(first))
        if made_by in _CHOICES:
            choices = arguments[-1].named_children if arguments and arguments[-1].type == "array" else []
            return TypeExpr(TypeKind.UNION, text, args=tuple(t for c in choices if (t := self.type_of(c))))
        if made_by == _LAZY and first is not None and first.type == "arrow_function":
            return self.type_of(first.child_by_field_name("body")) or TypeExpr(TypeKind.UNKNOWN, text)
        return TypeExpr(TypeKind.UNKNOWN, text)  # a shape with no name of its own, or one not known here

    def _fields(self, shape: Node | None) -> tuple[SchemaField, ...]:
        if shape is None or shape.type != "object":
            return ()
        found = []
        for pair in shape.named_children:
            key, value = pair.child_by_field_name("key"), pair.child_by_field_name("value")
            if pair.type != "pair" or key is None or value is None:
                continue
            name = _plain_text(key) or _text(key)
            described = self._described(value) if value.type == "call_expression" else None
            found.append(SchemaField(Identifier(name), self.type_of(value), described, pair))
        return tuple(found)

    def schema(self, value: Node | None) -> Schema | None:
        """The structure a value is, when it is a zod schema of one; None for anything else. Methods called on the
        schema after it is made, such as .strict(), leave it the structure it was."""
        if value is None or value.type != "call_expression":
            return None
        function, arguments = value.child_by_field_name("function"), self._arguments(value)
        made_by = self._zod(function)
        if made_by == _OBJECT or made_by in _STRICT_OBJECTS:
            return Schema(self._fields(next(iter(arguments), None)))
        if made_by == _ENUM:
            return Schema(members=tuple(Identifier(v) for v in _values(next(iter(arguments), None))))
        if made_by is not None or function is None or function.type != "member_expression":
            return None
        target, method = function.child_by_field_name("object"), _text(function.child_by_field_name("property"))
        if method == _EXTEND and target is not None and target.type in ("identifier", "member_expression"):
            base = self.resolve(target)
            return Schema(self._fields(next(iter(arguments), None)), base=base) if base is not None else None
        return self.schema(target)  # a method on a schema: the schema it was called on


def _values(written: Node | None) -> tuple[Written, ...]:
    """The values a literal or an enumeration is written with: one text, or a list of them."""
    if written is None:
        return ()
    one = _plain_text(written)
    if one is not None:
        return (Written(one),)
    return tuple(Written(v) for item in written.named_children if (v := _plain_text(item)) is not None) \
        if written.type == "array" else (Written(_text(written)),)


def read_schema(value: Node | None, resolve: Resolve) -> Schema | None:
    """The structure a constant's value is, when the value is a zod schema of one."""
    return _Reader(resolve).schema(value)
