"""One TypeScript file, read into the facts the code model holds: its symbols, what it imports and refers to, what
it calls, and the effects those calls start.

The file is parsed by tree-sitter, which reads text and nothing else: what is written is known, and what the
compiler would infer is not. So a value's type is known where the code says it, in an annotation or a `new`, as it
is for Python.

A file is read twice. Its outline is what other files need of it to follow their own imports: what it declares,
what its default export is, and what it only passes on from another module. Then each file is scanned with every
file's outline in hand.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from zigdag.adapters.typescript import apis, plans
from zigdag.adapters.typescript.schemas import Schema, read_schema
from zigdag.adapters.typescript.modules import Resolver
from zigdag.core.code import (
    CONSTRUCTOR_NAME,
    Abstraction,
    Access,
    AccessKind,
    Call,
    Computation,
    Dependency,
    DependencyKind,
    EffectStart,
    Field,
    Param,
    Place,
    PlannedUse,
    Qualified,
    Raise,
    Signature,
    Symbol,
    SymbolKind,
    SymbolName,
    TypeExpr,
    TypeKind,
    TypeOf,
    Unknown,
    Use,
    UseKind,
)
from zigdag.core.effects import Effect
from zigdag.core.findings import RecordPath, Span
from zigdag.core.measures import Column, Line, LineCount
from zigdag.core.names import Api, CodePath, Identifier
from zigdag.core.texts import FileText, Say, Written

TSX_SUFFIX = ".tsx"  # a file that may hold JSX, which is another grammar
_TYPESCRIPT = Language(tree_sitter_typescript.language_typescript())
_TSX = Language(tree_sitter_typescript.language_tsx())
ENCODING = "utf-8"

_FUNCTIONS = frozenset({"function_declaration", "generator_function_declaration"})
_FUNCTION_VALUES = frozenset({"arrow_function", "function_expression", "generator_function"})
_CLASSES = frozenset({"class_declaration", "abstract_class_declaration"})
_VARIABLES = frozenset({"lexical_declaration", "variable_declaration"})
_METHODS = frozenset({"method_definition", "abstract_method_signature", "method_signature"})
_PARAMETERS = frozenset({"required_parameter", "optional_parameter"})
_ASSIGNMENTS = frozenset({"assignment_expression", "augmented_assignment_expression"})
_NAMES = frozenset({"identifier", "type_identifier"})
_HIDDEN = frozenset({"private", "protected"})  # the modifiers that keep a member inside its class
_PRIVATE_NAME = "#"  # how a member that the language itself keeps private is named
_KEY_FIELD = "id"  # the field that is its structure's identity, when nothing says another is
_DEFAULT = "default"
_MAX_FORWARDS = 8  # how many modules a name is followed through before it is taken as written: barrels of barrels end
_THIS = "this"
_CONSTRUCTOR = "constructor"
_DOC_MARKS = "/*! \t"


def _text(node: Node | None) -> str:
    return node.text.decode(ENCODING) if node is not None and node.text is not None else ""


def _unquoted(node: Node | None) -> str | None:
    """What a string written as a plain constant says; None for anything else, such as a template with a value in
    it."""
    if node is None or node.type != "string":
        return None
    return "".join(_text(part) for part in node.named_children if part.type == "string_fragment")


@dataclass(frozen=True)
class Parsed:
    """A source file as the parser read it."""

    path: RecordPath
    unit: CodePath
    root: Node

    def span(self, node: Node) -> Span:
        row, column = node.start_point
        return Span(self.path, Line(row + 1), Column(column + 1))


def parse(path: RecordPath, unit: CodePath, text: FileText) -> Parsed | None:
    """A file's syntax; None when the parser cannot read all of it, so that nothing is taken from a file half
    read."""
    tree = Parser(_TSX if path.endswith(TSX_SUFFIX) else _TYPESCRIPT).parse(text.encode(ENCODING))
    return None if tree.root_node.has_error else Parsed(path, unit, tree.root_node)


def _declared_name(node: Node) -> str | None:
    """The name a declaration declares; None for one that declares several, or none."""
    return _text(node.child_by_field_name("name")) or None


def _declarations(statement: Node) -> Iterator[tuple[str, Node]]:
    """Each name a top-level statement declares, with the node that declares it: a variable statement declares one
    for each of its declarators."""
    if statement.type in _VARIABLES:
        for declarator in statement.named_children:
            name = declarator.child_by_field_name("name")
            if declarator.type == "variable_declarator" and name is not None and name.type == "identifier":
                yield _text(name), declarator
    elif (name := _declared_name(statement)) is not None:
        yield name, statement


def _source(statement: Node) -> str | None:
    """The module an import or a re-export names."""
    return _unquoted(statement.child_by_field_name("source"))


@dataclass(frozen=True)
class Outline:
    """What other files need to know of one file to follow their imports of it."""

    declared: frozenset[str]  # the names it declares at its top
    default: str | None  # the name its default export is declared under, when it has one with a name
    forwarded: Mapping[str, tuple[str, str]]  # a name it exports from another module -> that module, and the name there
    stars: tuple[str, ...]  # the modules whose every export it passes on
    exported: frozenset[str]  # the names it exports that it declares itself


def outline(parsed: Parsed) -> Outline:
    declared: set[str] = set()
    exported: set[str] = set()
    forwarded: dict[str, tuple[str, str]] = {}
    stars: list[str] = []
    default = None
    for statement in parsed.root.named_children:
        if statement.type != "export_statement":
            declared.update(name for name, _ in _declarations(statement))
            continue
        source, declaration = _source(statement), statement.child_by_field_name("declaration")
        clause = next((c for c in statement.named_children if c.type == "export_clause"), None)
        is_default = any(c.type == _DEFAULT for c in statement.children)
        if declaration is not None:
            names = [name for name, _ in _declarations(declaration)]
            declared.update(names)
            exported.update(names)
            default = names[0] if is_default and names else default
        elif clause is not None:
            for specifier in clause.named_children:
                name = _text(specifier.child_by_field_name("name"))
                alias = _text(specifier.child_by_field_name("alias")) or name
                if source is not None:
                    forwarded[alias] = (source, name)
                else:
                    exported.add(name)
        elif source is not None:
            stars.append(source)
        elif is_default:
            value = statement.child_by_field_name("value")
            default = _text(value) if value is not None and value.type == "identifier" else default
    return Outline(frozenset(declared), default, forwarded, tuple(stars), frozenset(exported))


@dataclass(frozen=True)
class Project:
    """Every file's outline, to follow a name to the module that declares it."""

    outlines: Mapping[CodePath, Outline]
    files: Mapping[CodePath, RecordPath]  # each module's own file
    resolver: Resolver
    contracts: frozenset[str] = frozenset({apis.CONTRACT_LIBRARY})  # the modules whose requires and ensures count

    def _exported(self, unit: CodePath, name: str, forwards: int) -> Qualified | None:
        """Where a name a module exports is declared, or None when the module has no such name to give."""
        here = self.outlines.get(unit)
        if here is None or forwards == 0:
            return None
        if name in here.declared:
            return Qualified(f"{unit}.{name}")
        passed = [here.forwarded[name]] if name in here.forwarded else [(star, name) for star in here.stars]
        for specifier, there in passed:
            target = self.resolver.resolve(self.files[unit], specifier).unit
            found = self._exported(target, there, forwards - 1) if target is not None else None
            if found is not None:
                return found
        return None

    def origin(self, unit: CodePath, name: str) -> Qualified:
        """The qualified name of what a module exports under a name: where it is declared, through the modules that
        only pass it on. A name that cannot be followed is taken as the module writes it."""
        return self._exported(unit, name, _MAX_FORWARDS) or Qualified(f"{unit}.{name}")

    def default_of(self, unit: CodePath) -> Qualified:
        """What importing a module's default gives: the declaration it exports as its default, or the module."""
        here = self.outlines.get(unit)
        return Qualified(f"{unit}.{here.default}") if here is not None and here.default else Qualified(unit)


@dataclass
class Facts:
    symbols: list[Symbol] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    effects: list[EffectStart] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    raises: list[Raise] = field(default_factory=list)
    accesses: list[Access] = field(default_factory=list)
    uses: list[Use] = field(default_factory=list)
    planned_uses: list[PlannedUse] = field(default_factory=list)
    computations: list[Computation] = field(default_factory=list)


class Scanner:
    """One file's walk. What it finds is in `facts`."""

    def __init__(self, parsed: Parsed, project: Project) -> None:
        self.parsed = parsed
        self.unit = parsed.unit
        self.project = project
        self.outline = project.outlines[parsed.unit]
        self.names: dict[str, Qualified] = {name: Qualified(f"{self.unit}.{name}") for name in self.outline.declared}
        self.places: list[Place] = [Place(self.unit, None)]
        self.classes: list[str] = []  # the class whose body is being read, when one is
        self.guarded = 0  # how many try blocks with a catch the code being read is inside
        self.types: list[dict[str, TypeOf]] = [{}]  # what each local name's value is known to be, per function
        self.schemas: frozenset[str] = frozenset()  # the constants of this file that are zod schemas of a structure
        self.facts = Facts()

    # ---- names ---------------------------------------------------------------------------------------------------

    @property
    def place(self) -> Place:
        return self.places[-1]

    def span(self, node: Node) -> Span:
        return self.parsed.span(node)

    def _target(self, specifier: str) -> tuple[CodePath | None, Qualified | None]:
        """What an import names: a module of the project, and in either case the name to qualify what it brings."""
        target = self.project.resolver.resolve(self.parsed.path, specifier)
        return target.unit, (Qualified(target.name) if target.name else None)

    def _import(self, statement: Node) -> None:
        """An import statement: a dependency on the module, and each name it brings bound to what it is there."""
        specifier = _source(statement)
        unit, base = self._target(specifier) if specifier is not None else (None, None)
        if base is None:
            return
        self._depends(base, DependencyKind.IMPORT, statement)
        clause = next((c for c in statement.named_children if c.type == "import_clause"), None)
        for part in clause.named_children if clause is not None else ():
            if part.type == "identifier":
                self.names[_text(part)] = self.project.default_of(unit) if unit is not None else base
            elif part.type == "namespace_import":
                self.names[_text(part.named_children[0])] = base
            elif part.type == "named_imports":
                for specifier_node in part.named_children:
                    name = _text(specifier_node.child_by_field_name("name"))
                    local = _text(specifier_node.child_by_field_name("alias")) or name
                    self.names[local] = (self.project.origin(unit, name) if unit is not None
                                         else Qualified(f"{base}.{name}"))

    def resolve(self, node: Node | None) -> Qualified | None:
        """What an expression or a type names, as far as this file says: an imported or declared name, a name that is
        there without being imported, or a member of either."""
        if node is None:
            return None
        if node.type in _NAMES:
            name = _text(node)
            return self.names.get(name) or (Qualified(name) if name in apis.GLOBALS else None)
        if node.type == _THIS:
            return Qualified(f"{self.unit}.{self.classes[-1]}") if self.classes else None
        if node.type == "member_expression":
            base = self.resolve(node.child_by_field_name("object"))
            return Qualified(f"{base}.{_text(node.child_by_field_name('property'))}") if base else None
        if node.type == "nested_type_identifier":
            base = self.resolve(node.child_by_field_name("module"))
            return Qualified(f"{base}.{_text(node.child_by_field_name('name'))}") if base else None
        if node.type == "generic_type":
            return self.resolve(node.child_by_field_name("name"))
        return None

    def _depends(self, target: Qualified, kind: DependencyKind, node: Node) -> None:
        self.facts.dependencies.append(Dependency(self.place, target, kind, self.span(node)))

    def _refers(self, node: Node) -> Qualified | None:
        """A reference, when what a name or a member names was imported or declared here; what it names either
        way."""
        named = self.resolve(node)
        root = node
        while root.type in ("member_expression", "nested_type_identifier", "generic_type"):
            root = root.child_by_field_name("object") or root.child_by_field_name("module") or \
                root.child_by_field_name("name") or root
            if root.type in _NAMES or root.type == _THIS:
                break
        if named is not None and root.type in _NAMES and _text(root) in self.names:
            self._depends(named, DependencyKind.REFERENCE, node)
        return named

    # ---- types ---------------------------------------------------------------------------------------------------

    def type_expr(self, node: Node | None) -> TypeExpr | None:
        """A type as written, in the code model's terms; None where none is written."""
        if node is None:
            return None
        text = Written(_text(node))
        kind = node.type
        if kind in ("type_annotation", "parenthesized_type", "readonly_type", "optional_type"):
            inner = next(iter(node.named_children), None)
            return self.type_expr(inner) or TypeExpr(TypeKind.UNKNOWN, text)
        if kind == "predefined_type" or (kind == "literal_type" and _text(node) in apis.NOTHING):
            return self._predefined(_text(node), text)
        if kind in ("type_identifier", "nested_type_identifier", "generic_type"):
            return self._named(node, text)
        if kind == "array_type" or kind == "tuple_type" or kind == "function_type":
            return TypeExpr(TypeKind.CONTAINER, text, args=self._types_in(node))
        if kind == "union_type":
            return self._union(node, text)
        if kind == "literal_type":
            return TypeExpr(TypeKind.LITERAL, text, values=(Written(text.strip("\"'`")),))
        if kind == "intersection_type":  # a branded type is the type it brands: string & { __brand: "OrderId" }
            plain = [a for a in self._types_in(node) if a.kind is not TypeKind.UNKNOWN]
            return plain[0] if len(plain) == 1 else TypeExpr(TypeKind.UNKNOWN, text)
        return TypeExpr(TypeKind.UNKNOWN, text)  # a shape with no name, or a type worked out from another

    def _types_in(self, node: Node) -> tuple[TypeExpr, ...]:
        """The types written directly inside a type: an array's element, a tuple's members, a function's
        parameters and what it returns."""
        found = []
        for child in node.named_children:
            if child.type == "formal_parameters":
                found += [self.type_expr(p.child_by_field_name("type")) for p in child.named_children]
            else:
                found.append(self.type_expr(child))
        return tuple(t for t in found if t is not None)

    @staticmethod
    def _predefined(name: str, text: Written) -> TypeExpr:
        if name == apis.TRUTH:
            return TypeExpr(TypeKind.BOOL, text)
        if name in apis.NOTHING:
            return TypeExpr(TypeKind.NONE, text)
        if name in apis.ANYTHING:
            return TypeExpr(TypeKind.ANY, text)
        return TypeExpr(TypeKind.REF, text, Qualified(f"{apis.BUILTINS_PREFIX}{name}"))

    def _named(self, node: Node, text: Written) -> TypeExpr:
        name = node.child_by_field_name("name") if node.type == "generic_type" else node
        written = _text(name)
        if written in apis.CONTAINERS and written not in self.names:
            arguments = node.child_by_field_name("type_arguments")
            return TypeExpr(TypeKind.CONTAINER, text, args=self._types_in(arguments) if arguments is not None else ())
        return TypeExpr(TypeKind.REF, text, self.resolve(name) or Qualified(written))

    def _union(self, node: Node, text: Written) -> TypeExpr:
        members: list[TypeExpr] = []
        for child in node.named_children:
            member = self.type_expr(child)
            members += member.args if member is not None and child.type == "union_type" and member.args else \
                [member] if member is not None else []
        if members and all(m.kind is TypeKind.LITERAL for m in members):  # an enumeration written as a union
            return TypeExpr(TypeKind.LITERAL, text, values=tuple(v for m in members for v in m.values))
        return TypeExpr(TypeKind.UNION, text, args=tuple(members))

    # ---- declarations --------------------------------------------------------------------------------------------

    def _description(self, node: Node) -> Say | None:
        """What the comment directly above a declaration says, in its first line."""
        above = node.prev_named_sibling
        if above is None or above.type != "comment" or above.end_point[0] < node.start_point[0] - 1:
            return None
        lines = [line.strip(_DOC_MARKS) for line in _text(above).splitlines()]
        return next((Say(line) for line in lines if line), None)

    def _size(self, node: Node) -> LineCount:
        return LineCount(node.end_point[0] - node.start_point[0] + 1)

    def _symbol(self, name: str, kind: SymbolKind, node: Node, documented: Node, public: bool, **more) -> None:
        self.facts.symbols.append(Symbol(self.unit, SymbolName(name), kind, public, self.span(node),
                                         self._size(node), self._description(documented), **more))

    def _parameters(self, node: Node) -> tuple[Param, ...]:
        found = []
        parameters = node.child_by_field_name("parameters")
        for parameter in parameters.named_children if parameters is not None else ():
            pattern = parameter.child_by_field_name("pattern")
            if parameter.type not in _PARAMETERS or pattern is None or pattern.type == _THIS:
                continue  # `this` is written as a parameter, and is not one
            found.append(Param(Identifier(_text(pattern).lstrip(".")), self.type_expr(parameter.child_by_field_name("type")),
                               self.span(parameter)))
        return tuple(found)

    def _signature(self, node: Node) -> Signature:
        return Signature(self._parameters(node), self.type_expr(node.child_by_field_name("return_type")),
                         self.span(node))

    def _parameter_types(self, node: Node) -> dict[str, TypeOf]:
        """What each parameter's value is known to be: the named type its annotation gives."""
        known = {}
        for parameter in self._parameters(node):
            named = parameter.type.named if parameter.type is not None else None
            if named is not None and not named.startswith(apis.BUILTINS_PREFIX):
                known[parameter.name] = TypeOf(named, False)
        return known

    def _used(self, node: Node, signature: Signature) -> Signature:
        """A signature, with what the function's body does with each of its parameters."""
        body = node.child_by_field_name("body")
        if body is None:
            return signature
        uses = plans.parameter_uses(body, [p.name for p in signature.params])
        return replace(signature, params=tuple(
            replace(p, branched_on=uses[p.name].branched_on, fields_read=uses[p.name].fields_read,
                    used_whole=uses[p.name].used_whole) for p in signature.params))

    def _trace(self, node: Node, signature: Signature, place: Place) -> None:
        """Where the values in a function's body come from, and what it works out."""
        body = node.child_by_field_name("body")
        if body is None:
            return
        owner = Qualified(f"{self.unit}.{self.classes[-1]}") if self.classes else None
        typed = {p.name: (p.type.named if p.type is not None else None) for p in signature.params}
        traced = plans.trace(body, typed, place, owner, self.resolve, self.value_type, self.span)
        self.facts.planned_uses += traced.planned_uses
        self.facts.computations += traced.computations

    def _contracted(self, node: Node) -> bool:
        """Whether a function states a contract: its body calls requires or ensures, from the library that has them
        or from the module the project names for its own."""
        body = node.child_by_field_name("body")
        stating = {f"{module}.{call}" for module in self.project.contracts for call in apis.CONTRACT_CALLS}
        return body is not None and any(
            inner.type == "call_expression" and self.resolve(inner.child_by_field_name("function")) in stating
            for inner in plans.inside(body))

    def _function(self, name: str, kind: SymbolKind, node: Node, documented: Node, public: bool) -> None:
        """A function or a method: its symbol, then its body, read as that function's own code."""
        signature = self._used(node, self._signature(node))
        self._symbol(name, kind, node, documented, public, signature=signature, contract=self._contracted(node))
        self.places.append(Place(self.unit, SymbolName(name)))
        self.types.append(self._parameter_types(node))
        for parameter in (node.child_by_field_name("parameters") or node).named_children:
            self.walk(parameter.child_by_field_name("value"))  # a default is worked out when the function is called
            self.walk(parameter.child_by_field_name("type"))
        self.walk(node.child_by_field_name("return_type"))
        self.walk(node.child_by_field_name("body"))
        self._trace(node, signature, self.place)
        self.types.pop()
        self.places.pop()

    def _field(self, node: Node) -> Field:
        name = _text(node.child_by_field_name("name") or node.child_by_field_name("pattern"))
        return Field(Identifier(name), self.type_expr(node.child_by_field_name("type")), self._description(node),
                     self.span(node), name == _KEY_FIELD)

    def _hidden(self, member: Node) -> bool:
        modifier = next((c for c in member.named_children if c.type == "accessibility_modifier"), None)
        name = _text(member.child_by_field_name("name"))
        return _text(modifier) in _HIDDEN or name.startswith(_PRIVATE_NAME)

    def _own_fields(self, constructor: Node) -> list[Field]:
        """The fields a constructor's parameters declare: each one written with a modifier is also a field."""
        parameters = constructor.child_by_field_name("parameters")
        return [self._field(p) for p in (parameters.named_children if parameters is not None else ())
                if any(c.type == "accessibility_modifier" or c.type == "readonly" for c in p.children)]

    def _class(self, name: str, node: Node, documented: Node, public: bool) -> None:
        body = node.child_by_field_name("body")
        members = body.named_children if body is not None else []
        heritage = next((c for c in node.named_children if c.type == "class_heritage"), None)
        bases = [self.type_expr_of_base(base) for clause in (heritage.named_children if heritage is not None else ())
                 for base in clause.named_children if base.type != "type_arguments"]
        fields = [self._field(m) for m in members if m.type == "public_field_definition"
                  and not any(c.type == "static" for c in m.children)]
        for member in members:
            if member.type == "method_definition" and _text(member.child_by_field_name("name")) == _CONSTRUCTOR:
                fields += self._own_fields(member)
        self._symbol(name, SymbolKind.CLASS, node, documented, public, fields=tuple(fields), bases=tuple(bases),
                     abstraction=Abstraction.ABSTRACT_BASE if node.type == "abstract_class_declaration" else None)
        self.walk(heritage)
        self.classes.append(name)
        for member in members:
            if member.type in _METHODS:
                written = _text(member.child_by_field_name("name"))
                method = CONSTRUCTOR_NAME if written == _CONSTRUCTOR else written
                self._function(f"{name}.{method}", SymbolKind.METHOD, member, member,
                               public and not self._hidden(member))
            else:
                self.walk(member)
        self.classes.pop()

    def type_expr_of_base(self, node: Node) -> TypeExpr:
        """A base as a class names it: an expression after `extends`, a type after `implements`."""
        return TypeExpr(TypeKind.REF, Written(_text(node)), self.resolve(node) or Qualified(_text(node)))

    def _shape(self, name: str, node: Node, body: Node | None, documented: Node, public: bool) -> None:
        """A structure written as a shape: an interface, or a type alias of an object type. Its properties are its
        fields; one that also asks for methods is a protocol, implemented by having them."""
        members = body.named_children if body is not None else []
        methods = [m for m in members if m.type == "method_signature"]
        heritage = [base for clause in node.named_children if clause.type == "extends_type_clause"
                    for base in clause.named_children if base.type != "type_arguments"]
        self._symbol(name, SymbolKind.CLASS, node, documented, public,
                     fields=tuple(self._field(m) for m in members if m.type == "property_signature"),
                     bases=tuple(self.type_expr_of_base(base) for base in heritage),
                     abstraction=Abstraction.PROTOCOL if methods else None)
        for base in heritage:
            self._refers(base)
        for member in members:
            if member.type == "method_signature":
                self._function(f"{name}.{_text(member.child_by_field_name('name'))}", SymbolKind.METHOD, member,
                               member, public)
            else:
                self.walk(member)

    def _structure(self, name: str, node: Node, documented: Node, public: bool, schema: Schema) -> None:
        """A structure written as a zod schema: its keys are its fields, and what it extends is its base."""
        fields = tuple(Field(f.name, f.type, f.description or self._description(f.node), self.span(f.node),
                             f.name == _KEY_FIELD) for f in schema.fields)
        bases = (TypeExpr(TypeKind.REF, Written(schema.base), schema.base),) if schema.base is not None else ()
        self._symbol(name, SymbolKind.CLASS, node, documented, public, fields=fields, bases=bases,
                     members=schema.members)

    def _declare(self, name: str, node: Node, documented: Node) -> None:
        """One top-level declaration: its symbol, and whatever its body holds."""
        public = name in self.outline.exported
        value = node.child_by_field_name("value")
        if node.type in _FUNCTIONS:
            self._function(name, SymbolKind.FUNCTION, node, documented, public)
        elif node.type == "variable_declarator" and value is not None and value.type in _FUNCTION_VALUES:
            self._function(name, SymbolKind.FUNCTION, value, documented, public)
        elif node.type == "variable_declarator" and name in self.schemas:
            self._structure(name, node, documented, public, read_schema(value, self.resolve) or Schema())
            self.walk(value)
        elif node.type == "variable_declarator":
            self._symbol(name, SymbolKind.CONSTANT, node, documented, public)
            self.walk(node.child_by_field_name("type"))
            self.walk(value)
        elif node.type in _CLASSES:
            self._class(name, node, documented, public)
        elif node.type == "interface_declaration":
            self._shape(name, node, node.child_by_field_name("body"), documented, public)
        elif node.type == "type_alias_declaration" and value is not None and value.type == "object_type":
            self._shape(name, node, value, documented, public)
        elif node.type == "type_alias_declaration" and name in self.schemas:
            self.walk(value)  # the type taken from a schema of the same name: the schema is the structure
        elif node.type == "type_alias_declaration":
            self._symbol(name, SymbolKind.NAMED_TYPE, node, documented, public)
            self.walk(value)
        elif node.type == "enum_declaration":
            body = node.child_by_field_name("body")
            members = tuple(Identifier(_text(m.child_by_field_name("name") or m))
                            for m in (body.named_children if body is not None else ()) if m.type != "comment")
            self._symbol(name, SymbolKind.CLASS, node, documented, public, members=members)
        else:
            self.walk(node)

    def imported(self) -> tuple[Qualified, ...]:
        """What the file imports, without the rest of it being read: each module or library, and each name brought
        from one, as what it is where it is declared. For a test file, this says which code the test can run."""
        declared = set(self.names.values())
        for statement in self.parsed.root.named_children:
            if statement.type == "import_statement":
                self._import(statement)
        return (*(d.target for d in self.facts.dependencies), *(q for q in self.names.values() if q not in declared))

    def scan(self) -> Facts:
        for statement in self.parsed.root.named_children:
            if statement.type == "import_statement":
                self._import(statement)
        self.schemas = frozenset(
            name for statement in self.parsed.root.named_children
            for name, node in _declarations(statement.child_by_field_name("declaration") or statement)
            if node.type == "variable_declarator" and read_schema(node.child_by_field_name("value"),
                                                                    self.resolve) is not None)
        for statement in self.parsed.root.named_children:
            declaration = statement.child_by_field_name("declaration") if statement.type == "export_statement" \
                else statement
            if statement.type == "import_statement":
                continue
            if statement.type == "export_statement" and declaration is None:
                specifier = _source(statement)
                base = self._target(specifier)[1] if specifier is not None else None
                if base is not None:  # passing another module's names on depends on that module
                    self._depends(base, DependencyKind.IMPORT, statement)
                self.walk(statement.child_by_field_name("value"))
                continue
            declared = list(_declarations(declaration)) if declaration is not None else []
            for name, node in declared:
                self._declare(name, node, statement)
            if not declared:
                self.walk(declaration)
        return self.facts

    # ---- what the code does --------------------------------------------------------------------------------------

    def value_type(self, node: Node | None) -> TypeOf | None:
        """What this file says about an expression's type: a typed local, `this`, a `new`, a call, a field."""
        if node is None:
            return None
        if node.type == "identifier":
            return self.types[-1].get(_text(node))
        if node.type == _THIS and self.classes:
            return TypeOf(Qualified(f"{self.unit}.{self.classes[-1]}"), False)
        if node.type == "member_expression":
            base = self.value_type(node.child_by_field_name("object"))
            return base.field(Identifier(_text(node.child_by_field_name("property")))) if base is not None else None
        if node.type == "new_expression" or node.type == "call_expression":
            callee = self.resolve(node.child_by_field_name("constructor") or node.child_by_field_name("function"))
            return TypeOf(callee, True) if callee is not None and callee.split(".")[0] not in apis.GLOBALS else None
        if node.type in ("parenthesized_expression", "non_null_expression", "await_expression"):
            return self.value_type(next(iter(node.named_children), None))
        return None

    def _bind(self, declarator: Node) -> None:
        """Note what a local variable's value is known to be, from its annotation or from what it is given."""
        name = declarator.child_by_field_name("name")
        if name is None or name.type != "identifier" or len(self.types) == 1:
            return
        annotated = self.type_expr(declarator.child_by_field_name("type"))
        named = annotated.named if annotated is not None else None
        known = (TypeOf(named, False) if named is not None and not named.startswith(apis.BUILTINS_PREFIX)
                 else self.value_type(declarator.child_by_field_name("value")))
        if known is None:
            self.types[-1].pop(_text(name), None)
        else:
            self.types[-1][_text(name)] = known

    def _changes(self, holder: Node | None, name: Node | None, in_place: bool, node: Node) -> None:
        """A change to a field of a value whose type is known."""
        value = self.value_type(holder)
        if value is not None and name is not None:
            self.facts.accesses.append(Access(self.place, value, Identifier(_text(name)), AccessKind.UPDATES,
                                              in_place, self.span(node)))

    def _use(self, value: Node, kind: UseKind, via: str, effect: Effect | None) -> None:
        """A value given to a release point or an effect. A variable whose type is unknown is kept as unknown;
        anything else of unknown type, such as a constant, cannot hold a protected value read from elsewhere."""
        known = self.value_type(value)
        if known is not None or value.type in ("identifier", "member_expression"):
            self.facts.uses.append(Use(self.place, known, kind, Api(via), effect, self.span(value)))

    def _given(self, arguments: Node | None, callee: Qualified, effect: Effect | None) -> None:
        """What a call is given, where the call releases it or has an effect: each argument is used that way."""
        for argument in arguments.named_children if arguments is not None else ():
            if effect is not None:
                self._use(argument, UseKind.EFFECT, callee, effect)
            if callee in apis.RELEASES:
                self._use(argument, UseKind.RELEASE, callee, None)

    def _effect(self, effect: Effect | None, via: str, node: Node) -> None:
        if effect is not None:
            self.facts.effects.append(EffectStart(self.place, effect, Api(via), self.span(node)))

    def _unknown(self, what: str, node: Node) -> None:
        self.facts.unknowns.append(Unknown(self.place, Written(what), self.span(node)))

    def _loads(self, how: str, node: Node) -> None:
        """A module loaded by a call, require("x") or import("x"): a dependency when its name is written out, and
        code that cannot be read when it is worked out."""
        arguments = node.child_by_field_name("arguments")
        specifier = _unquoted(next(iter(arguments.named_children), None)) if arguments is not None else None
        base = self._target(specifier)[1] if specifier is not None else None
        if base is not None:
            self._depends(base, DependencyKind.IMPORT, node)
        elif specifier is None:
            self._unknown(how, node)

    def _call(self, node: Node) -> None:
        function, arguments = node.child_by_field_name("function"), node.child_by_field_name("arguments")
        if function is not None and (function.type == apis.DYNAMIC_IMPORT or _text(function) == apis.REQUIRE):
            self._loads(_text(function), node)
        else:
            callee = self._refers(function) if function is not None else None
            if callee is not None:
                self.facts.calls.append(Call(self.place, callee, self.span(node)))
                self._effect(apis.effect_of(callee), callee, node)
                self._given(arguments, callee, apis.effect_of(callee))
                if callee in apis.UNKNOWN_CALLS:
                    self._unknown(callee, node)
            elif function is not None:
                self._member_parts(function)
            if function is not None and function.type == "member_expression" and _text(
                    function.child_by_field_name("property")) in apis.RELEASING_METHODS:
                released = function.child_by_field_name("object")  # order.toString() releases the order
                if released is not None:
                    self._use(released, UseKind.RELEASE, f".{_text(function.child_by_field_name('property'))}()", None)
            if function is not None and function.type == "member_expression" and _text(
                    function.child_by_field_name("property")) in apis.MUTATORS:
                changed = function.child_by_field_name("object")  # order.lines.push(line) changes order's lines
                if changed is not None and changed.type == "member_expression":
                    self._changes(changed.child_by_field_name("object"), changed.child_by_field_name("property"),
                                  True, node)
        self.walk(arguments)

    def _new(self, node: Node) -> None:
        constructor, arguments = node.child_by_field_name("constructor"), node.child_by_field_name("arguments")
        callee = self._refers(constructor) if constructor is not None else None
        if callee is not None:
            self.facts.calls.append(Call(self.place, callee, self.span(node)))
            takes_none = arguments is None or not arguments.named_children
            self._effect(apis.TIME if callee == apis.CLOCK and takes_none else apis.effect_of(callee),
                         f"new {callee}", node)
            if callee in apis.UNKNOWN_CALLS:
                self._unknown(f"new {callee}", node)
        else:
            self.walk(constructor)
        self.walk(arguments)

    def _member_parts(self, node: Node) -> None:
        """Read what a member is of, when the member as a whole names nothing known: a().b, items[0].name."""
        if node.type == "member_expression":
            self.walk(node.child_by_field_name("object"))
        else:
            self.walk(node)

    def _member(self, node: Node) -> None:
        named = self._refers(node)
        if named is None:
            self._member_parts(node)
            return
        touched = next((effect for name, effect in apis.TOUCHED.items()
                        if named == name or named.startswith(f"{name}.")), None)
        self._effect(touched, named, node)

    def _throw(self, node: Node) -> None:
        thrown = next(iter(node.named_children), None)
        if thrown is not None and thrown.type == "new_expression":
            constructor = thrown.child_by_field_name("constructor")
            error = TypeExpr(TypeKind.REF, Written(_text(constructor)),
                             self.resolve(constructor) or Qualified(_text(constructor)))
            self.facts.raises.append(Raise(self.place, error, self.guarded > 0, self.span(node)))
        self.walk(thrown)

    def _try(self, node: Node) -> None:
        catches = node.child_by_field_name("handler") is not None  # a catch takes whatever is thrown
        self.guarded += catches
        self.walk(node.child_by_field_name("body"))
        self.guarded -= catches
        self.walk(node.child_by_field_name("handler"))
        self.walk(node.child_by_field_name("finalizer"))

    def walk(self, node: Node | None) -> None:
        """Read a piece of code that declares no symbol of its own, as the code of the place being read."""
        if node is None:
            return
        kind = node.type
        if kind == "call_expression":
            self._call(node)
        elif kind == "new_expression":
            self._new(node)
        elif kind == "member_expression":
            self._member(node)
        elif kind in _NAMES:
            self._refers(node)
        elif kind in ("nested_type_identifier", "generic_type"):
            self._refers(node)
            self.walk(node.child_by_field_name("type_arguments"))
        elif kind == "template_substitution":
            for value in node.named_children:  # a value written into a text is released there
                self._use(value, UseKind.RELEASE, apis.TEMPLATE, None)
                self.walk(value)
        elif kind == "throw_statement":
            self._throw(node)
        elif kind == "try_statement":
            self._try(node)
        elif kind in _ASSIGNMENTS:
            target = node.child_by_field_name("left")
            if target is not None and target.type == "member_expression":
                self._changes(target.child_by_field_name("object"), target.child_by_field_name("property"), False,
                              node)
                self.walk(target.child_by_field_name("object"))
            self.walk(node.child_by_field_name("right"))
        elif kind == "variable_declarator":
            self.walk(node.child_by_field_name("type"))
            self.walk(node.child_by_field_name("value"))
            self._bind(node)
        elif kind in _PARAMETERS:  # of a function written inside the one being read: its name declares, not refers
            self.walk(node.child_by_field_name("type"))
            self.walk(node.child_by_field_name("value"))
        elif kind in _FUNCTIONS | _CLASSES | _METHODS:  # declared inside the code being read: read as part of it
            for child in node.named_children:
                if child != node.child_by_field_name("name"):
                    self.walk(child)
        else:
            for child in node.named_children:
                self.walk(child)
