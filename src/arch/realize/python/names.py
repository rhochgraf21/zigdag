"""What the names in Python source refer to.

Realizes arch.realize.python.names. A module's scope maps each name to the dotted name it stands for:
its imports and its own definitions, and inside a function also `self` and typed parameters. The
extractor resolves calls and effects through the same scope; a review asks for `references` to explain
each name on a changed line, including which line set a local variable's value.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import NewType, TypeAlias

from arch.realize.facts import Column, LineNo, NameKind, Reference, SourceLocation, SourcePath, SourceText, Text, UnitName

DottedName = NewType("DottedName", str)  # a module path and the names after it, such as `arch.model.ids.Text`
Scope: TypeAlias = dict[str, str]  # each name as written, to the dotted name it stands for
_LINE_END = re.compile(r"\r\n|\r|\n")  # as Python counts lines; str.splitlines also splits on form feeds


def source_lines(text: SourceText) -> tuple[SourceText, ...]:
    """The lines of a source file as Python numbers them."""
    return tuple(SourceText(line) for line in _LINE_END.split(text))


def references(path: SourcePath, text: SourceText, unit: UnitName) -> tuple[Reference, ...]:
    """The resolved names in one file, for reading its changes. Not part of extracting facts: only a review needs them."""
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError):
        return ()
    package = unit if path.endswith("__init__.py") else UnitName(unit.rpartition(".")[0])
    return tuple(_references(tree, unit, package, path, source_lines(text)))


def module_scope(tree: ast.Module, unit: UnitName, package: UnitName) -> Scope:
    """Module-level names -> dotted names: imports, plus the module's own functions and classes."""
    names: Scope = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                parts = package.split(".") if package else []
                base = ".".join(parts[: max(0, len(parts) - (node.level - 1))])
                module = ".".join(p for p in (base, node.module or "") if p)
            for a in node.names:
                if a.name != "*":
                    names[a.asname or a.name] = f"{module}.{a.name}" if module else a.name
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names[node.name] = f"{unit}.{node.name}"
    return names


def function_scope(fn: ast.FunctionDef | ast.AsyncFunctionDef, owner: DottedName | None, module: Scope) -> Scope:
    """The names a function adds to its module's scope: `self` or `cls` as its class (`owner`), and each
    parameter whose annotation names a class."""
    local: Scope = {}
    params = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
    for i, a in enumerate(params):
        if i == 0 and owner and a.arg in ("self", "cls"):
            local[a.arg] = owner
        elif a.annotation is not None and (typ := _annotation_type(a.annotation, module)):
            local[a.arg] = typ
    return local


def dotted(expr: ast.expr, scope: Scope) -> DottedName | None:
    """The dotted name an expression refers to, through imports and known local types; None if unknown."""
    parts: list[str] = []
    while True:
        if isinstance(expr, ast.Attribute):
            parts.append(expr.attr)
            expr = expr.value
        elif isinstance(expr, ast.Call):  # Cls(...).method -> Cls.method
            expr = expr.func
        elif isinstance(expr, ast.Name):
            base = scope.get(expr.id)
            return DottedName(".".join([base, *reversed(parts)])) if base else None
        else:
            return None


def _references(tree: ast.Module, unit: UnitName, package: UnitName, path: SourcePath, lines: tuple[str, ...]):
    """Each name on one line that resolves to a dotted target: imported or defined names, attributes of
    typed parameters and of `self`, and the parameters themselves (as values of their type)."""
    module_names = module_scope(tree, unit, package)
    for node in tree.body:  # module values are names too, for reading (calls and effects do not need them)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        module_names.update({t.id: f"{unit}.{t.id}" for t in targets if isinstance(t, ast.Name) and t.id not in module_names})

    def column(line: int, offset: int) -> Column:
        text = lines[line - 1] if 0 < line <= len(lines) else ""
        return Column(offset if text.isascii() else len(text.encode()[:offset].decode(errors="ignore")))

    def emit(nodes, local: dict[str, str], bound: dict[str, list[_Binding]] | None = None):
        scope, values = {**module_names, **local}, set(local)
        for root in nodes:
            for node in ast.walk(root):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    if (typ := dotted(node.value.func, scope)) is not None:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                scope[target.id], _ = typ, values.add(target.id)
                if not (isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load)):
                    continue
                if isinstance(node, ast.Name) and bound and (b := _binding_at(bound.get(node.id, ()), node.lineno)):
                    if b.line != node.lineno:  # set on the same line: nothing to add
                        start, end = column(node.lineno, node.col_offset), column(node.lineno, node.end_col_offset or 0)
                        yield Reference(unit, Text(node.id), Text(b.source or ""), NameKind.LOCAL,
                                        SourceLocation(path, LineNo(node.lineno)), start, end, LineNo(b.line), Text(b.text))
                    continue
                if node.end_lineno != node.lineno or (target := dotted(node, scope)) is None:
                    continue
                start, end = column(node.lineno, node.col_offset), column(node.lineno, node.end_col_offset or 0)
                kind = NameKind.VALUE if isinstance(node, ast.Name) and node.id in values else NameKind.DEFINITION
                text = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                yield Reference(unit, Text(text[start:end]), Text(target), kind,
                                SourceLocation(path, LineNo(node.lineno)), start, end)

    def signature_parts(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
        args = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs, fn.args.vararg, fn.args.kwarg]
        return [*(a.annotation for a in args if a is not None and a.annotation is not None),
                *([fn.returns] if fn.returns else []), *fn.decorator_list]

    def function(fn: ast.FunctionDef | ast.AsyncFunctionDef, owner: str | None):
        local = function_scope(fn, DottedName(owner) if owner else None, module_names)
        yield from emit(signature_parts(fn), {})
        bound = _local_bindings(fn, lines, {**module_names, **local})
        yield from emit([*fn.body, *fn.args.defaults, *(d for d in fn.args.kw_defaults if d is not None)], local, bound)

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from function(node, None)
        elif isinstance(node, ast.ClassDef):
            yield from emit([*node.decorator_list, *node.bases], {})
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield from function(item, f"{unit}.{node.name}")
                else:
                    yield from emit([item], {})
        elif not isinstance(node, ast.Import | ast.ImportFrom):
            yield from emit([node], {})


_BINDING_CHARS = 100  # of the setting line shown when a local is pointed at


@dataclass(frozen=True)
class _Binding:
    line: int
    text: str  # the line that sets the value, as written
    source: str | None  # the dotted name of what was called to produce it


def _local_bindings(fn: ast.FunctionDef | ast.AsyncFunctionDef, lines: tuple[str, ...], scope: Scope):
    """Each local name -> the lines that set it, in order: assignments, loop and `with` targets, comprehensions."""
    out: dict[str, list[_Binding]] = {}

    def add(target: ast.AST, at: ast.AST, value: ast.AST | None, last: ast.AST | None = None) -> None:
        """`last` is the node that ends the setting part: for a loop, its iterable, not its body."""
        line = at.lineno
        text = lines[line - 1].strip() if line <= len(lines) else ""
        if (getattr(last or at, "end_lineno", None) or line) > line or len(text) > _BINDING_CHARS:
            text = text[:_BINDING_CHARS].rstrip() + " …"
        source = dotted(value.func, scope) if isinstance(value, ast.Call) else None
        for n in ast.walk(target):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                out.setdefault(n.id, []).append(_Binding(line, text, source))

    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                add(t, node, node.value)
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr) and node.value is not None:
            add(node.target, node, node.value)
        elif isinstance(node, ast.For | ast.AsyncFor):
            add(node.target, node, None, node.iter)
        elif isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                if item.optional_vars is not None:
                    add(item.optional_vars, node, item.context_expr, node.items[-1].context_expr)
        elif isinstance(node, ast.comprehension):
            add(node.target, node.target, None)
    return {k: sorted(v, key=lambda b: b.line) for k, v in out.items()}


def _binding_at(bindings, line: int) -> _Binding | None:
    """The binding a use on `line` sees: the last one at or before it (loops aside, which is enough to read by)."""
    before = [b for b in bindings if b.line <= line]
    return before[-1] if before else None


def _annotation_type(annotation: ast.expr, names: Scope) -> DottedName | None:
    """The dotted class an annotation names, for `x: Cls` and `x: Cls | None`; else None."""
    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        left, right = annotation.left, annotation.right
        if isinstance(right, ast.Constant) and right.value is None:
            return _annotation_type(left, names)
        return None
    parts: list[str] = []
    while isinstance(annotation, ast.Attribute):
        parts.append(annotation.attr)
        annotation = annotation.value
    if isinstance(annotation, ast.Name) and annotation.id in names:
        return DottedName(".".join([names[annotation.id], *reversed(parts)]))
    return None
