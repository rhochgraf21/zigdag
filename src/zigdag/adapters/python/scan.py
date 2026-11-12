"""Reading one Python module into the code model: its symbols, dependencies, calls, effects and raises."""

from __future__ import annotations

import ast
import builtins
import io
import tokenize
from dataclasses import dataclass, field

from zigdag.adapters.python import apis, plans, resources
from zigdag.core.code import (
    Abstraction,
    Access,
    AccessKind,
    Call,
    Computation,
    Dependency,
    DependencyKind,
    EffectStart,
    Field,
    Link,
    Param,
    Place,
    PlannedUse,
    Qualified,
    Raise,
    Signature,
    Symbol,
    SymbolKind,
    SymbolName,
    Test,
    TestId,
    TypeExpr,
    TypeKind,
    TypeOf,
    Unknown,
    Use,
    UseKind,
    ResourceUse,
)
from zigdag.core.effects import Effect
from zigdag.core.findings import Digest, RecordPath, Span, digest_of
from zigdag.core.names import CodePath
from zigdag.core.record.model import EvidenceKind

_BUILTINS = frozenset(dir(builtins))


def comments_by_line(text: str) -> dict[int, str]:
    """1-based line -> the text of the comment on it."""
    out: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string[1:].strip()
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return out


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
    contracts: list[Test] = field(default_factory=list)
    resource_uses: list[ResourceUse] = field(default_factory=list)


def _longest(table, name: str):
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        hit = table.get(".".join(parts[:i]))
        if hit is not None:
            return hit
    return None


@dataclass(frozen=True)
class _Uses:
    """What a function's body does with one of its parameters."""

    branched_on: bool
    fields_read: tuple[str, ...]
    used_whole: bool


def _branch_tests(body: list[ast.stmt]) -> list[ast.expr]:
    """What the body takes branches by: the tests of if, elif, while and conditional expressions, and match subjects."""
    out: list[ast.expr] = []
    for node in (n for stmt in body for n in ast.walk(stmt)):
        if isinstance(node, ast.If | ast.IfExp | ast.While):
            out.append(node.test)
        elif isinstance(node, ast.Match):
            out.append(node.subject)
    return out


def _tested(test: ast.expr) -> set[str]:
    """The names a branch picks by: flag, not flag, kind == "x", kind is Kind.A, and either side of and and or."""
    if isinstance(test, ast.Name):
        return {test.id}
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _tested(test.operand)
    if isinstance(test, ast.BoolOp):
        return {name for value in test.values for name in _tested(value)}
    if isinstance(test, ast.Compare) and len(test.comparators) == 1:
        sides = (test.left, test.comparators[0])
        names = [s.id for s in sides if isinstance(s, ast.Name)]
        fixed = [s for s in sides if isinstance(s, ast.Constant | ast.Attribute)]
        return set(names) if len(names) == 1 and fixed else set()
    return set()


def _uses(body: list[ast.stmt], names: list[str]) -> dict[str, _Uses]:
    """For each parameter: whether the body branches on it, the fields of it the body reads, and whether the body
    also uses it whole. Reading a field is `p.total`; calling `p.total()` uses p whole, as passing p on does."""
    parents = {child: parent for stmt in body for parent in ast.walk(stmt) for child in ast.iter_child_nodes(parent)}
    reads: dict[str, list[str]] = {n: [] for n in names}
    whole: set[str] = set()
    for node in (n for stmt in body for n in ast.walk(stmt)):
        if not isinstance(node, ast.Name) or node.id not in reads:
            continue
        holder = parents.get(node)
        called = isinstance(holder, ast.Attribute) and isinstance(parents.get(holder), ast.Call) and \
            parents[holder].func is holder
        if isinstance(node.ctx, ast.Load) and isinstance(holder, ast.Attribute) and isinstance(holder.ctx, ast.Load) \
                and not called:
            if holder.attr not in reads[node.id]:
                reads[node.id].append(holder.attr)
        else:
            whole.add(node.id)
    tested = {name for test in _branch_tests(body) for name in _tested(test)}
    return {n: _Uses(n in tested, tuple(reads[n]), n in whole) for n in names}


def written(text: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Digest:
    """A digest of a function as it is written, from its first decorator to its last line. What a test verifies, and
    what a contract promises, are said in decorators, so a function whose decorators changed has changed too."""
    first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return digest_of(*text.splitlines()[first - 1:node.end_lineno or node.lineno])


class Scanner(ast.NodeVisitor):
    def __init__(self, unit: CodePath, package: str, path: RecordPath, tree: ast.Module, text: str):
        self.unit = unit
        self.text = text
        self.package = package
        self.path = path
        self.tree = tree
        self.comments = comments_by_line(text)
        self.names: dict[str, str] = {}
        self.exported: frozenset[str] | None = None
        self.places: list[Place] = [Place(unit, None)]
        self.classes: list[str] = []  # local class names, outermost first
        self.handlers: list[frozenset[str] | None] = []  # None catches everything
        self.types: list[dict[str, TypeOf]] = [{}]  # what each local name's value is known to be, per function
        self.loggers: set[str] = set()  # module names bound to a logger
        self.facts = Facts()
        self._statement_lines = frozenset(n.lineno for n in ast.walk(tree) if isinstance(n, ast.stmt))
        self._collect_names()
        self.resources = resources.Tracker(self.resolve)
        for node in tree.body:  # a module's own clients and settings are bound before any function uses them
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    self.resources.assigned(target, node.value)

    # ---- names -------------------------------------------------------------------------------------------------

    def _relative(self, module: str | None, level: int) -> str:
        if not level:
            return module or ""
        base = self.package.split(".") if self.package else []
        base = base[: len(base) - (level - 1)] if level > 1 else base
        return ".".join([*base, *([module] if module else [])])

    def _collect_names(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        self.names[a.asname] = a.name
                    else:
                        top = a.name.split(".")[0]
                        self.names.setdefault(top, top)
            elif isinstance(node, ast.ImportFrom):
                base = self._relative(node.module, node.level)
                for a in node.names:
                    if a.name != "*":
                        self.names[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                self.names[node.name] = f"{self.unit}.{node.name}"
            elif isinstance(node, ast.Assign):
                for unpacked in (t for t in node.targets if isinstance(t, ast.Tuple | ast.List)):
                    for element in (e for e in unpacked.elts if isinstance(e, ast.Name)):
                        self.names[element.id] = f"{self.unit}.{element.id}"  # CASES, SEED = 50, 0
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.names[target.id] = f"{self.unit}.{target.id}"
                        if isinstance(node.value, ast.Call) and self.resolve(node.value.func) in apis.LOGGER_FACTORIES:
                            self.loggers.add(f"{self.unit}.{target.id}")
                        if target.id == "__all__" and isinstance(node.value, ast.List | ast.Tuple):
                            self.exported = frozenset(e.value for e in node.value.elts
                                                      if isinstance(e, ast.Constant) and isinstance(e.value, str))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                self.names[node.target.id] = f"{self.unit}.{node.target.id}"
            elif hasattr(ast, "TypeAlias") and isinstance(node, ast.TypeAlias):
                self.names[node.name.id] = f"{self.unit}.{node.name.id}"

    def resolve(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in self.names:
                return self.names[node.id]
            return f"{apis.BUILTINS_PREFIX}{node.id}" if node.id in _BUILTINS else None
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in apis.RECEIVERS and self.classes:
                return f"{self.unit}.{'.'.join(self.classes)}.{node.attr}"
            base = self.resolve(node.value)
            return f"{base}.{node.attr}" if base else None
        return None

    # ---- helpers -----------------------------------------------------------------------------------------------

    @property
    def place(self) -> Place:
        return self.places[-1]

    def span(self, node: ast.AST) -> Span:
        return Span(self.path, getattr(node, "lineno", 1), getattr(node, "col_offset", 0) + 1)

    def _inside_function(self) -> bool:
        return self.place.symbol is not None and not (self.classes and len(self.places) == 1)

    def effect(self, effect: Effect, via: str, node: ast.AST) -> None:
        self.facts.effects.append(EffectStart(self.place, effect, via, self.span(node)))

    def _description(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            doc = ast.get_docstring(node)
            return doc.strip().splitlines()[0] if doc and doc.strip() else None
        line = getattr(node, "lineno", 0)
        return self.comments.get(getattr(node, "end_lineno", line)) or self.comments.get(line) or (
            self.comments.get(line - 1) if line - 1 in self.comments and self._only_comment(line - 1) else None)

    def _only_comment(self, line: int) -> bool:
        return line not in self._statement_lines

    def _public(self, name: str, module_level: bool) -> bool:
        if name.startswith("_"):
            return False
        return not (module_level and self.exported is not None and name not in self.exported)

    # ---- types -------------------------------------------------------------------------------------------------

    def type_expr(self, node: ast.expr) -> TypeExpr:
        text = ast.unparse(node)
        if isinstance(node, ast.Constant) and node.value is None:
            return TypeExpr(TypeKind.NONE, text)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                return self.type_expr(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                return TypeExpr(TypeKind.UNKNOWN, text)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return TypeExpr(TypeKind.UNION, text, args=(self.type_expr(node.left), self.type_expr(node.right)))
        if isinstance(node, ast.Name | ast.Attribute):
            name = self.resolve(node)
            if name is None:
                return TypeExpr(TypeKind.UNKNOWN, text)
            if name in apis.BOOLS:
                return TypeExpr(TypeKind.BOOL, text, Qualified(name))
            if name in apis.ANYS:
                return TypeExpr(TypeKind.ANY, text, Qualified(name))
            if name in apis.CONTAINERS:
                return TypeExpr(TypeKind.CONTAINER, text, Qualified(name))
            return TypeExpr(TypeKind.REF, text, Qualified(name))
        if isinstance(node, ast.Subscript):
            name = self.resolve(node.value)
            items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            flat: list[ast.expr] = []
            for item in items:
                flat += item.elts if isinstance(item, ast.List) else [item]
            args = tuple(self.type_expr(a) for a in flat if not (isinstance(a, ast.Constant) and a.value is ...))
            if name in apis.UNIONS:
                extra = (TypeExpr(TypeKind.NONE, "None"),) if name == "typing.Optional" else ()
                return TypeExpr(TypeKind.UNION, text, Qualified(name), args + extra)
            if name in apis.LITERALS:
                values = tuple(str(a.value) for a in flat if isinstance(a, ast.Constant))
                return TypeExpr(TypeKind.LITERAL, text, Qualified(name), values=values)
            if name in apis.ANNOTATED and args:
                return args[0]
            if name in apis.CONTAINERS:
                return TypeExpr(TypeKind.CONTAINER, text, Qualified(name), args)
            if name is None:
                return TypeExpr(TypeKind.UNKNOWN, text)
            return TypeExpr(TypeKind.REF, text, Qualified(name), args)
        return TypeExpr(TypeKind.UNKNOWN, text)

    def signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef, method: bool) -> Signature:
        a = node.args
        params = [*a.posonlyargs, *a.args, *([a.vararg] if a.vararg else []), *a.kwonlyargs,
                  *([a.kwarg] if a.kwarg else [])]
        static = any(self.resolve(d) == apis.STATICMETHOD for d in node.decorator_list)
        if method and not static and params and params[0].arg in apis.RECEIVERS:
            params = params[1:]
        uses = _uses(node.body, [p.arg for p in params])
        return Signature(
            tuple(Param(p.arg, self.type_expr(p.annotation) if p.annotation else None, self.span(p),
                        uses[p.arg].branched_on, uses[p.arg].fields_read, uses[p.arg].used_whole) for p in params),
            self.type_expr(node.returns) if node.returns else None,
            self.span(node),
        )

    # ---- definitions -------------------------------------------------------------------------------------------

    def _decorators(self, node) -> tuple[tuple[Effect, ...] | None, tuple[TypeExpr, ...] | None, bool, list[Link]]:
        effects = errors = None
        contract = False
        links: list[Link] = []
        for d in node.decorator_list:
            target = d.func if isinstance(d, ast.Call) else d
            name = self.resolve(target) or ""
            args = d.args if isinstance(d, ast.Call) else []
            if name == apis.DEAL_HAS:
                effects = tuple(Effect(a.value) for a in args if isinstance(a, ast.Constant) and isinstance(a.value, str))
            elif name == apis.DEAL_PURE:
                effects, errors = (), ()
            elif name == apis.DEAL_SAFE:
                errors = ()
            elif name == apis.DEAL_RAISES:
                errors = tuple(self.type_expr(a) for a in args)
            elif name in apis.DEAL_CONTRACTS:
                contract = True
            elif name.split(".")[-1] == "verifies":
                links += [Link(a.value, self.span(a)) for a in args
                          if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        return effects, errors, contract, links

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for d in node.decorator_list:
            self.visit(d)
        defining = len(self.places) == 1  # a module-level function, or a method of a module-level class
        if defining:
            method = bool(self.classes)
            name = SymbolName(".".join([*self.classes, node.name]))
            effects, errors, contract, links = self._decorators(node)
            public = self._public(node.name, not method) and (not method or all(not c.startswith("_")
                                                                                for c in self.classes))
            self.facts.symbols.append(Symbol(
                self.unit, name, SymbolKind.METHOD if method else SymbolKind.FUNCTION, public, self.span(node),
                (node.end_lineno or node.lineno) - node.lineno + 1, self._description(node),
                self.signature(node, method), declared_effects=effects, declared_errors=errors, contract=contract,
                unmutated=self._unmutated(node)))
            if contract and links:
                self.facts.contracts.append(Test(TestId(f"{self.unit}::{name}"), tuple(links),
                                                 EvidenceKind.CONTRACT, (), self.span(node), Place(self.unit, name),
                                                 written(self.text, node)))
            self.places.append(Place(self.unit, name))
        for arg in [*node.args.defaults, *node.args.kw_defaults]:
            if arg is not None:
                self.visit(arg)
        self.types.append(self._parameter_types(node, defining and bool(self.classes)))
        for stmt in node.body:
            self.visit(stmt)
        if defining:
            owner = Qualified(f"{self.unit}.{'.'.join(self.classes)}") if self.classes else None
            traced = plans.trace(self, node, Place(self.unit, name), owner)
            self.facts.planned_uses += traced.planned_uses
            self.facts.computations += traced.computations
        self.types.pop()
        if defining:
            self.places.pop()

    def _unmutated(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[Span, ...]:
        """The lines of a function marked not to be mutated."""
        lines = range(node.lineno, (node.end_lineno or node.lineno) + 1)
        return tuple(Span(self.path, line, 1) for line in lines if apis.NO_MUTATE in self.comments.get(line, ""))

    def _parameter_types(self, node: ast.FunctionDef | ast.AsyncFunctionDef, method: bool) -> dict[str, TypeOf]:
        """The names a function starts with whose types are known: its annotated parameters, and self."""
        known = dict(self.types[-1])  # a nested function sees the names of the function around it
        a = node.args
        params = [*a.posonlyargs, *a.args, *a.kwonlyargs]
        static = any(self.resolve(d) == apis.STATICMETHOD for d in node.decorator_list)
        if method and not static and params:
            known[params[0].arg] = TypeOf(Qualified(f"{self.unit}.{'.'.join(self.classes)}"), False)
            params = params[1:]
        for p in params:
            typed = self._annotated(p.annotation) if p.annotation is not None else None
            if typed is None:
                known.pop(p.arg, None)
            else:
                known[p.arg] = typed
        return known

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for d in node.decorator_list:
            self.visit(d)
        for b in node.bases:
            self.visit(b)
        if len(self.places) != 1:  # a class inside a function belongs to that function
            self.generic_visit(node)
            return
        name = ".".join([*self.classes, node.name])
        fields = tuple(
            Field(s.target.id, self.type_expr(s.annotation), self._description(s), self.span(s), self._is_key(s))
            for s in node.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
        )
        bases = tuple(self.type_expr(b) for b in node.bases)
        members = ()
        if any(b.name in apis.ENUM_BASES for b in bases):
            members = tuple(t.id for s in node.body if isinstance(s, ast.Assign) for t in s.targets
                            if isinstance(t, ast.Name) and not t.id.startswith("_"))
        self.facts.symbols.append(Symbol(
            self.unit, SymbolName(name), SymbolKind.CLASS,
            self._public(node.name, not self.classes) and all(not c.startswith("_") for c in self.classes),
            self.span(node), (node.end_lineno or node.lineno) - node.lineno + 1, self._description(node),
            fields=fields, bases=bases, members=members, abstraction=self._abstraction(node, bases),
            contract=any(self.resolve(d.func if isinstance(d, ast.Call) else d) in apis.DEAL_CONTRACTS
                         for d in node.decorator_list)))
        self.classes.append(node.name)
        for stmt in node.body:
            self.visit(stmt)
        self.classes.pop()

    def _abstraction(self, node: ast.ClassDef, bases: tuple[TypeExpr, ...]) -> Abstraction | None:
        """A protocol, an abstract base class, or neither."""
        named = {b.name for b in bases}
        if named & apis.PROTOCOLS:
            return Abstraction.PROTOCOL
        metaclass = next((self.resolve(k.value) for k in node.keywords if k.arg == apis.METACLASS), None)
        abstract_method = any(self.resolve(d.func if isinstance(d, ast.Call) else d) in apis.ABSTRACT_METHODS
                              for s in node.body if isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef)
                              for d in s.decorator_list)
        if named & apis.ABSTRACT_BASES or metaclass in apis.ABSTRACT_METACLASSES or abstract_method:
            return Abstraction.ABSTRACT_BASE
        return None

    def _is_key(self, node: ast.AnnAssign) -> bool:
        """Whether a field is its class's identity: named id, or marked as a primary key."""
        marked = isinstance(node.value, ast.Call) and any(
            k.arg == apis.PRIMARY_KEY and isinstance(k.value, ast.Constant) and k.value.value is True
            for k in node.value.keywords)
        return marked or (isinstance(node.target, ast.Name) and node.target.id == apis.KEY_FIELD)

    def _module_assignment(self, node: ast.Assign | ast.AnnAssign) -> None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name) or target.id == "__all__":
                continue
            value = node.value
            maker = self.resolve(value.func) if isinstance(value, ast.Call) else None
            annotation = self.resolve(node.annotation) if isinstance(node, ast.AnnAssign) else None
            typed = maker in apis.NAMED_TYPE_MAKERS or annotation in apis.TYPE_ALIAS or (
                target.id[:1].isupper() and not target.id.isupper()
                and isinstance(value, ast.Subscript | ast.BinOp)
                and self.type_expr(value).kind in (TypeKind.UNION, TypeKind.CONTAINER, TypeKind.REF))
            kind = SymbolKind.NAMED_TYPE if typed else SymbolKind.CONSTANT
            self.facts.symbols.append(Symbol(
                self.unit, SymbolName(target.id), kind, self._public(target.id, True), self.span(node),
                (node.end_lineno or node.lineno) - node.lineno + 1, self._description(node)))

    def visit_Assign(self, node: ast.Assign) -> None:
        if len(self.places) == 1 and not self.classes:
            self._module_assignment(node)
        self.generic_visit(node)
        for target in node.targets:
            self._bind(target, self.value_type(node.value))
            self.resources.assigned(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if len(self.places) == 1 and not self.classes:
            self._module_assignment(node)
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.annotation)
        self.visit(node.target)
        self._bind(node.target, self._annotated(node.annotation))

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.generic_visit(node)
        self._bind(node.target, None)

    visit_AsyncFor = visit_For

    def visit_TypeAlias(self, node) -> None:  # noqa: ANN001 (ast.TypeAlias exists from Python 3.12)
        self.facts.symbols.append(Symbol(self.unit, SymbolName(node.name.id), SymbolKind.NAMED_TYPE,
                                         self._public(node.name.id, True), self.span(node), 1,
                                         self._description(node)))

    # ---- values ------------------------------------------------------------------------------------------------

    def _annotated(self, annotation: ast.expr) -> TypeOf | None:
        named = self.type_expr(annotation).named
        return TypeOf(named, False) if named is not None and not named.startswith(apis.BUILTINS_PREFIX) else None

    def value_type(self, node: ast.expr) -> TypeOf | None:
        """What this file says about an expression's type: a typed local, a constructor or function call, a field."""
        if isinstance(node, ast.Name):
            return self.types[-1].get(node.id)
        if isinstance(node, ast.Attribute):
            base = self.value_type(node.value)
            return base.field(node.attr) if base is not None else None
        if isinstance(node, ast.Call):
            callee = self.resolve(node.func)
            return TypeOf(Qualified(callee), True) if callee and not callee.startswith(apis.BUILTINS_PREFIX) else None
        return None

    def _bind(self, target: ast.expr, value: TypeOf | None) -> None:
        if not isinstance(target, ast.Name) or len(self.types) == 1:
            return
        if value is None:
            self.types[-1].pop(target.id, None)
        else:
            self.types[-1][target.id] = value

    def _access(self, holder: ast.expr, name: str | None, kind: AccessKind, in_place: bool, node: ast.AST) -> None:
        value = self.value_type(holder)
        if value is not None:
            self.facts.accesses.append(Access(self.place, value, name, kind, in_place, self.span(node)))

    def _use(self, value: ast.expr, kind: UseKind, via: str, effect: Effect | None) -> None:
        """A value given to a release point or an effect. A variable whose type is unknown is kept as unknown;
        anything else of unknown type, such as a constant, cannot hold a protected value read from elsewhere."""
        known = self.value_type(value)
        if known is not None or isinstance(value, ast.Name | ast.Attribute):
            self.facts.uses.append(Use(self.place, known, kind, via, effect, self.span(value)))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self._use(part.value, UseKind.RELEASE, apis.F_STRING, None)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
            for item in node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]:
                self._use(item, UseKind.RELEASE, apis.PERCENT_FORMAT, None)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, ast.Store | ast.Del) and isinstance(node.value, ast.Attribute):
            self._access(node.value.value, node.value.attr, AccessKind.UPDATES, True, node)
        self.generic_visit(node)

    def visit_Delete(self, node: ast.Delete) -> None:
        self.generic_visit(node)
        for target in node.targets:
            self._bind(target, None)

    # ---- uses --------------------------------------------------------------------------------------------------

    def _import(self, node: ast.Import | ast.ImportFrom, targets: list[str]) -> None:
        for target in targets:
            self.facts.dependencies.append(Dependency(self.place, Qualified(target), DependencyKind.IMPORT,
                                                      self.span(node)))
        if self._inside_function():
            self.effect(apis.IMPORT, "import", node)

    def visit_Import(self, node: ast.Import) -> None:
        self._import(node, [a.name for a in node.names])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = self._relative(node.module, node.level)
        self._import(node, [f"{base}.{a.name}" if base and a.name != "*" else base or a.name for a in node.names])

    def _reference(self, name: str, node: ast.AST) -> None:
        if not (name == self.unit or name.startswith(self.unit + ".") or name.startswith(apis.BUILTINS_PREFIX)):
            self.facts.dependencies.append(Dependency(self.place, Qualified(name), DependencyKind.REFERENCE,
                                                      self.span(node)))
        touched = _longest(apis.TOUCHED, name)
        if touched is not None:
            self.effect(touched, name, node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and (name := self.resolve(node)) is not None:
            self._reference(name, node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if not isinstance(node.ctx, ast.Load):
            self._access(node.value, node.attr, AccessKind.UPDATES, False, node)
            self.generic_visit(node)
            return
        self._access(node.value, node.attr, AccessKind.READS, False, node)
        name = self.resolve(node)
        if name is None:
            self.generic_visit(node)
            return
        self._reference(name, node)
        inner = node.value  # a resolved chain is not visited further, but each field read along it still counts
        while isinstance(inner, ast.Attribute):
            self._access(inner.value, inner.attr, AccessKind.READS, False, inner)
            inner = inner.value

    def visit_Call(self, node: ast.Call) -> None:
        callee = self.resolve(node.func)
        effect, via = self._call_effect(node, callee)
        if callee is not None:
            self.facts.calls.append(Call(self.place, Qualified(callee), self.span(node)))
            if callee in apis.UNKNOWN_CALLS:
                self.facts.unknowns.append(Unknown(self.place, callee.removeprefix(apis.BUILTINS_PREFIX),
                                                   self.span(node)))
        if effect is not None:
            self.effect(effect, via, node)
        arguments = [*node.args, *(k.value for k in node.keywords)]
        touched = _longest(apis.TOUCHED, callee) if callee is not None else None
        if effect is not None or touched is not None:
            for a in arguments:
                self._use(a, UseKind.EFFECT, via or callee or "", effect or touched)
        if callee in apis.RELEASES or self._formats(node.func):
            for a in arguments:
                self._use(a, UseKind.RELEASE, (callee or apis.FORMAT_METHOD).removeprefix(apis.BUILTINS_PREFIX), None)
        self._changes(node, callee)
        client_call = self.resources.call(node)
        if client_call is not None:
            self.facts.resource_uses.append(ResourceUse(self.place, client_call.access, client_call.via,
                                                        client_call.setting, self.span(node)))
        self.generic_visit(node)

    def _call_effect(self, node: ast.Call, callee: str | None) -> tuple[Effect | None, str]:
        """The effect a call starts, and the API it starts with."""
        if callee in apis.OPENERS:
            return self._open_effect(node), callee.removeprefix(apis.BUILTINS_PREFIX)
        if callee == "builtins.print":
            return self._print_effect(node), "print"
        if callee is not None and (effect := _longest(apis.CALLS, callee)) is not None:
            return effect, callee
        if callee is not None and any(callee.startswith(logger + ".") for logger in self.loggers):
            return apis.STDERR, apis.LOGGING
        if isinstance(node.func, ast.Attribute) and node.func.attr in apis.PATH_METHODS and (
                callee is None or callee.startswith("pathlib.")):
            return apis.PATH_METHODS[node.func.attr], f".{node.func.attr}()"
        return None, ""

    @staticmethod
    def _formats(func: ast.expr) -> bool:
        """"...".format(...)"""
        return isinstance(func, ast.Attribute) and func.attr == "format" and isinstance(func.value, ast.Constant) and \
            isinstance(func.value.value, str)

    def _changes(self, node: ast.Call, callee: str | None) -> None:
        """Changes a call makes to a field: order.lines.append(line), setattr(order, "total", 0)."""
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in apis.MUTATORS and isinstance(func.value, ast.Attribute):
            self._access(func.value.value, func.value.attr, AccessKind.UPDATES, True, node)
        if callee in apis.SETATTR and node.args:
            name = node.args[1] if len(node.args) > 1 else None
            field_name = name.value if isinstance(name, ast.Constant) and isinstance(name.value, str) else None
            self._access(node.args[0], field_name, AccessKind.UPDATES, False, node)

    def _open_effect(self, node: ast.Call) -> Effect:
        mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
        if mode is None:
            return apis.READ
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
            return apis.WRITE if set(mode.value) & set("wax+") else apis.READ
        return apis.WRITE  # a mode that cannot be read: assume the stronger effect

    def _print_effect(self, node: ast.Call) -> Effect:
        target = next((k.value for k in node.keywords if k.arg == "file"), None)
        if target is None:
            return apis.STDOUT
        name = self.resolve(target)
        return {"sys.stderr": apis.STDERR, "sys.stdout": apis.STDOUT}.get(name or "", apis.WRITE)

    def visit_Global(self, node: ast.Global) -> None:
        self.effect(apis.GLOBAL, "global", node)

    # `nonlocal` is not an effect here: a nested function is charged to the function around it, and nonlocal
    # can only change that function's own variables.

    def _caught(self, name: str | None) -> bool:
        for handler in self.handlers:
            if handler is None or {"builtins.Exception", "builtins.BaseException"} & handler:
                return True
            if name and (name in handler or name.split(".")[-1] in {h.split(".")[-1] for h in handler}):
                return True
        return False

    def visit_Raise(self, node: ast.Raise) -> None:
        if node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            name = self.resolve(target)
            error = TypeExpr(TypeKind.REF, ast.unparse(target), Qualified(name)) if name else TypeExpr(
                TypeKind.UNKNOWN, ast.unparse(target))
            self.facts.raises.append(Raise(self.place, error, self._caught(name), self.span(node)))
        self.generic_visit(node)

    def _try(self, node: ast.Try) -> None:
        caught: set[str] = set()
        everything = False
        for h in node.handlers:
            if h.type is None:
                everything = True
            for t in (h.type.elts if isinstance(h.type, ast.Tuple) else [h.type] if h.type else []):
                if (name := self.resolve(t)) is not None:
                    caught.add(name)
        self.handlers.append(None if everything else frozenset(caught))
        for stmt in node.body:
            self.visit(stmt)
        self.handlers.pop()
        for part in (*node.handlers, *node.orelse, *node.finalbody):
            self.visit(part)

    visit_Try = _try
    visit_TryStar = _try


def scan(unit: CodePath, package: str, path: RecordPath, text: str) -> tuple[Facts | None, str | None]:
    """The module's facts, or None and why it could not be read."""
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as e:
        return None, f"line {e.lineno}: {e.msg}"
    scanner = Scanner(unit, package, path, tree, text)
    for stmt in tree.body:
        scanner.visit(stmt)
    return scanner.facts, None
