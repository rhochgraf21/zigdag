"""Units, imports, public API, contracts and design links from Python source.

Realizes arch.realize.python.extract. Uses the stdlib `ast` and never imports or runs user code.
Effects are charged to the code that obtains access to an effectful API (see this component's
decisions), and calls are recorded so realize can propagate effects across the project.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize

from arch.realize.facts import (
    Alias,
    Call,
    Capability,
    Column,
    ContractDecl,
    Definition,
    DesignLink,
    Effect,
    EffectUse,
    Exposure,
    Reach,
    Facts,
    Import,
    ImportForm,
    Language,
    LineNo,
    NameKind,
    Optionality,
    Parameter,
    ParseError,
    PublicSymbol,
    Reference,
    Role,
    SourceLocation,
    SourcePath,
    SourceText,
    SymbolName,
    Text,
    TypeRef,
    Unit,
    UnitName,
    UnitShape,
)

LANGUAGE = Language("python")
CAPABILITIES = frozenset(Capability)
_LINE_END = re.compile(r"\r\n|\r|\n")  # as Python counts lines; str.splitlines also splits on form feeds
_CONTRACT_KINDS = frozenset({"pre", "post", "ensure", "inv", "has", "raises", "reason", "pure", "safe", "example"})


def extract(path: SourcePath, text: SourceText, unit: UnitName, role: Role) -> Facts:
    def at(node: ast.AST) -> SourceLocation:
        return SourceLocation(path, LineNo(getattr(node, "lineno", 1)))

    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError) as e:
        line = LineNo(getattr(e, "lineno", None) or 1)
        loc = SourceLocation(path, line)
        return Facts(
            units=(Unit(unit, path, LANGUAGE, role, frozenset()),),
            errors=(ParseError(path, Text(f"{type(e).__name__}: {e}"), loc),),
        )

    package = unit if path.endswith("__init__.py") else UnitName(unit.rpartition(".")[0])
    imports = tuple(_imports(tree, unit, package, at))
    deal_names = _deal_aliases(tree)
    symbols: list[PublicSymbol] = []
    contracts: list[ContractDecl] = []
    links: list[DesignLink] = []
    definitions: list[Definition] = []
    comments = _trailing_comments(text)

    exported = _dunder_all(tree)
    public_names: set[str] = set()
    for node, qual in _definitions(tree):
        owner, _, name = qual.rpartition(".")
        top = not owner
        if top:
            public = (name in exported) if exported is not None else not name.startswith("_")
        else:
            public = owner in public_names and not name.startswith("_")  # a member of a private class is private
        if public:
            public_names.add(qual)
        definitions.append(_definition(node, qual, unit, path, comments))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and public:
            kind, signature = _signature(node, qual)
            params, returns = _parameters(node), _type_ref(node.returns)
            symbols.append(PublicSymbol(unit, SymbolName(qual), kind, signature, at(node), params, returns))
        elif isinstance(node, ast.ClassDef) and public:
            symbols.append(PublicSymbol(unit, SymbolName(qual), *_signature(node, qual), at(node)))
        elif isinstance(node, ast.AnnAssign) and public and not top:
            symbols.append(PublicSymbol(unit, SymbolName(qual), Text("field"), Text(f"{qual}: {ast.unparse(node.annotation)}"),
                                        at(node), (), _type_ref(node.annotation)))
        elif isinstance(node, ast.Assign | ast.AnnAssign) and public and top and name != "__all__":
            symbols.append(PublicSymbol(unit, SymbolName(qual), Text("value"), Text(name), at(node)))
        for dec in getattr(node, "decorator_list", ()):
            if (kind := _contract_kind(dec, deal_names)) is not None:
                call_args = dec.args if isinstance(dec, ast.Call) else []
                args = ", ".join(ast.unparse(a) for a in call_args)
                literals = tuple(Text(a.value) for a in call_args if isinstance(a, ast.Constant) and isinstance(a.value, str))
                contracts.append(ContractDecl(unit, SymbolName(qual), Text(kind), Text(args), at(dec), literals))
            for target in _realizes_targets(dec):
                links.append(DesignLink(unit, SymbolName(qual), Text(target), at(dec)))

    effects, calls = _effects_and_calls(tree, unit, package, at)
    doc = ast.get_docstring(tree)
    summary = Text(next((line.strip() for line in doc.splitlines() if line.strip()), "")) if doc else None
    shape = UnitShape.PACKAGE if path.endswith("__init__.py") else UnitShape.MODULE
    return Facts(
        units=(Unit(unit, path, LANGUAGE, role, CAPABILITIES, summary or None, shape),),
        imports=imports,
        symbols=tuple(symbols),
        contracts=tuple(contracts),
        links=tuple(links),
        effects=effects,
        calls=calls,
        aliases=tuple(_aliases(tree, unit, package, at)),
        definitions=tuple(definitions),
    )


def names(path: SourcePath, text: SourceText, unit: UnitName) -> tuple[Reference, ...]:
    """The resolved names in one file, for reading its changes. Not part of `extract`: only a review needs them."""
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError):
        return ()
    package = unit if path.endswith("__init__.py") else UnitName(unit.rpartition(".")[0])
    return tuple(_references(tree, unit, package, path, _LINE_END.split(text)))


def _imports(tree: ast.Module, unit: UnitName, package: UnitName, at):
    """Every import anywhere in the module. `from x import y` targets `x.y`; consumers resolve the
    longest prefix that names a known unit, which covers both submodules and attributes."""
    for node in ast.walk(tree):
        end = LineNo(getattr(node, "end_lineno", None) or getattr(node, "lineno", 1))
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield Import(unit, UnitName(alias.name), at(node), ImportForm.MODULE, end)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".") if package else []
                if node.level - 1 > len(parts):
                    continue  # beyond the top of the project; Python would fail too
                base = ".".join(parts[: len(parts) - (node.level - 1)])
                module = ".".join(p for p in (base, node.module or "") if p)
            else:
                module = node.module or ""
            if module == "__future__":
                continue
            for alias in node.names:
                if alias.name == "*":
                    yield Import(unit, UnitName(module), at(node), ImportForm.MODULE, end)
                else:
                    yield Import(unit, UnitName(".".join(p for p in (module, alias.name) if p)), at(node), ImportForm.NAME, end)


def _definitions(tree: ast.Module):
    """Module-level and class-level definitions with qualified names (not nested functions)."""
    def walk(body, prefix):
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                yield node, prefix + node.name
            elif isinstance(node, ast.ClassDef):
                yield node, prefix + node.name
                yield from walk(node.body, prefix + node.name + ".")
            elif isinstance(node, ast.AnnAssign) and prefix and isinstance(node.target, ast.Name):
                yield node, prefix + node.target.id  # a class-level field
            elif isinstance(node, ast.Assign) and not prefix:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        yield node, t.id
            elif isinstance(node, ast.AnnAssign) and not prefix and isinstance(node.target, ast.Name):
                yield node, node.target.id
    yield from walk(tree.body, "")


def _definition(node: ast.AST, qual: str, unit: UnitName, path: SourcePath, comments: dict[int, str]) -> Definition:
    """Where a definition starts and ends, how it reads, and the first line of what it says about itself."""
    start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", ()))])
    end = LineNo(node.end_lineno or node.lineno)
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        kind, signature = _signature(node, qual)
        doc = ast.get_docstring(node)
        summary = next((line.strip() for line in doc.splitlines() if line.strip()), None) if doc else None
    else:
        annotation = f": {ast.unparse(node.annotation)}" if isinstance(node, ast.AnnAssign) else ""
        kind = "field" if "." in qual else "exports" if qual == "__all__" else "value"
        signature = f"{qual}{annotation}"
        summary = comments.get(node.lineno) or comments.get(end)
    return Definition(unit, SymbolName(qual), Text(kind), Text(signature), SourceLocation(path, LineNo(start)), end,
                      Text(summary) if summary else None)


def _trailing_comments(text: str) -> dict[int, str]:
    """line -> the comment that ends it, for comments that follow code on the same line."""
    out: dict[int, str] = {}
    code_lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and tok.start[0] in code_lines:
                out[tok.start[0]] = tok.string.lstrip("#").strip()
            elif tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT):
                code_lines.add(tok.start[0])
    except (tokenize.TokenError, SyntaxError, ValueError):  # UnicodeDecodeError is a ValueError
        pass
    return out


def _dunder_all(tree: ast.Module) -> frozenset[str] | None:
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            value = node.value
            if isinstance(value, ast.List | ast.Tuple):
                return frozenset(e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return None


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, qual: str) -> tuple[Text, Text]:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in (*node.bases, *node.keywords))
        return Text("class"), Text(f"class {node.name}({bases})" if bases else f"class {node.name}")
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    kind = "method" if "." in qual else "function"
    return Text(kind), Text(f"{prefix}{qual}({ast.unparse(node.args)}){returns}")


def _deal_aliases(tree: ast.Module) -> tuple[frozenset[str], dict[str, str]]:
    """(names bound to the deal module, local name -> contract kind for decorators imported from deal)."""
    modules, direct = {"deal"}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "deal")
        elif isinstance(node, ast.ImportFrom) and node.module == "deal" and not node.level:
            direct.update({a.asname or a.name: a.name for a in node.names if a.name in _CONTRACT_KINDS})
    return frozenset(modules), direct


def _contract_kind(dec: ast.expr, deal_names: tuple[frozenset[str], dict[str, str]]) -> str | None:
    modules, direct = deal_names
    func = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in modules:
        return func.attr if func.attr in _CONTRACT_KINDS else None
    if isinstance(func, ast.Name):
        return direct.get(func.id)
    return None


def _realizes_targets(dec: ast.expr) -> list[str]:
    if not isinstance(dec, ast.Call):
        return []
    func = dec.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
    if name != "realizes":
        return []
    return [a.value for a in dec.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]


# Effects. Dotted names (after resolving imports) that are, or are inside, these APIs.
_SOURCES: dict[str, Effect] = {
    **dict.fromkeys(["os.environ", "os.getenv", "os.putenv", "os.unsetenv", "os.getcwd", "os.chdir", "sys.argv",
                     "pathlib.Path.cwd", "pathlib.Path.home", "os.path.expanduser"], Effect.ENV),
    **dict.fromkeys(["os.listdir", "os.scandir", "os.walk", "os.stat", "os.lstat", "os.path.exists", "os.path.isfile",
                     "os.path.isdir", "os.path.getsize", "os.path.getmtime", "os.path.realpath", "glob", "fnmatch.filter"],
                    Effect.FS_READ),
    **dict.fromkeys(["os.remove", "os.unlink", "os.mkdir", "os.makedirs", "os.rename", "os.replace", "os.rmdir",
                     "os.removedirs", "os.symlink", "os.link", "os.truncate", "shutil", "tempfile"], Effect.FS_WRITE),
    **dict.fromkeys(["subprocess", "os.system", "os.popen", "os.execv", "os.execvp", "os.spawnv", "os.fork", "os.kill",
                     "multiprocessing"], Effect.SUBPROCESS),
    **dict.fromkeys(["socket", "ssl", "http.client", "http.server", "urllib.request", "ftplib", "smtplib", "requests",
                     "httpx", "aiohttp", "urllib3", "websockets"], Effect.NETWORK),
    **dict.fromkeys(["time.time", "time.time_ns", "time.monotonic", "time.monotonic_ns", "time.perf_counter",
                     "time.process_time", "time.sleep", "time.localtime", "time.gmtime", "time.ctime", "time.asctime",
                     "datetime.datetime.now", "datetime.datetime.today", "datetime.datetime.utcnow", "datetime.date.today"],
                    Effect.TIME),
    **dict.fromkeys(["random", "secrets", "uuid.uuid1", "uuid.uuid4", "os.urandom"], Effect.RANDOM),
    **dict.fromkeys(["sys.stdout", "sys.stderr", "sys.stdin", "logging"], Effect.STDIO),
    **dict.fromkeys(["importlib.import_module", "importlib.__import__", "builtins.eval", "builtins.exec"], Effect.UNKNOWN),
}
_BUILTINS: dict[str, Effect] = {"print": Effect.STDIO, "input": Effect.STDIO, "breakpoint": Effect.STDIO,
                                "eval": Effect.UNKNOWN, "exec": Effect.UNKNOWN, "__import__": Effect.UNKNOWN}
# pathlib methods distinctive enough to count on any receiver, in units that use pathlib at all.
_PATH_READ = frozenset({"read_text", "read_bytes", "iterdir", "glob", "rglob", "is_dir", "is_file", "exists", "stat",
                        "samefile", "readlink"})
_PATH_WRITE = frozenset({"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "touch", "symlink_to",
                         "hardlink_to", "chmod"})
_MODULE = SymbolName("<module>")


def _source_of(dotted: str) -> Effect | None:
    name = dotted
    while name:
        if name in _SOURCES:
            return _SOURCES[name]
        name = name.rpartition(".")[0]
    return None


def _bindings(tree: ast.Module, unit: UnitName, package: UnitName) -> dict[str, str]:
    """Module-level names -> dotted names: imports, plus the module's own functions and classes."""
    names: dict[str, str] = {}
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


def _effects_and_calls(tree: ast.Module, unit: UnitName, package: UnitName, at):
    module_names = _bindings(tree, unit, package)
    uses_pathlib = any(v == "pathlib" or v.startswith("pathlib.") for v in module_names.values())
    effects: dict[tuple[SymbolName, Effect], EffectUse] = {}
    calls: dict[tuple[SymbolName, str, int], Call] = {}

    def scan(symbol: SymbolName, nodes, local: dict[str, str]) -> None:
        scope = {**module_names, **local}

        def dotted(expr: ast.expr) -> str | None:
            return _dotted(expr, scope)

        def effect(kind: Effect, node: ast.AST) -> None:
            effects.setdefault((symbol, kind), EffectUse(unit, symbol, kind, Reach.DIRECT, at(node)))

        def call(name: str, node: ast.AST) -> None:
            calls.setdefault((symbol, name, node.lineno), Call(unit, symbol, Text(name), at(node), LineNo(node.end_lineno or node.lineno)))

        for root in nodes:
            for node in ast.walk(root):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    if (typ := dotted(node.value.func)) is not None:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                scope[target.id] = typ  # x = Cls(...): later x.m() is Cls.m
                if isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load):
                    if (name := dotted(node)) is not None and (kind := _source_of(name)) is not None:
                        effect(kind, node)
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Name) and func.id not in scope and func.id in _BUILTINS:
                    effect(_BUILTINS[func.id], node)
                elif isinstance(func, ast.Name) and func.id == "open" and "open" not in scope:
                    effect(_open_mode(node), node)
                if isinstance(func, ast.Attribute) and uses_pathlib and dotted(func) is None:
                    if func.attr in _PATH_READ:
                        effect(Effect.FS_READ, node)
                    elif func.attr in _PATH_WRITE:
                        effect(Effect.FS_WRITE, node)
                    elif func.attr == "open":
                        effect(_open_mode(node, offset=0), node)
                if (name := dotted(func)) is not None:
                    call(name, node)
                if symbol == _MODULE:
                    continue  # at import time a function passed along is stored, not run
                for arg in (*node.args, *(k.value for k in node.keywords)):
                    if isinstance(arg, ast.Name | ast.Attribute) and (name := dotted(arg)) is not None:
                        call(name, arg)  # a callback may be called by the callee; count it (over-approximation)

    def function_locals(fn: ast.FunctionDef | ast.AsyncFunctionDef, owner: str | None) -> dict[str, str]:
        local: dict[str, str] = {}
        args = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
        for i, a in enumerate(args):
            if i == 0 and owner and a.arg in ("self", "cls"):
                local[a.arg] = owner
            elif a.annotation is not None and (typ := _annotation_type(a.annotation, module_names)):
                local[a.arg] = typ
        return local

    def body_of(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
        # The body and defaults run; annotations and decorators are not calls made by this function.
        return [*fn.body, *fn.args.defaults, *(d for d in fn.args.kw_defaults if d is not None)]

    module_level = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            scan(SymbolName(node.name), body_of(node), function_locals(node, None))
            module_level += node.decorator_list
        elif isinstance(node, ast.ClassDef):
            owner = f"{unit}.{node.name}"
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    scan(SymbolName(f"{node.name}.{item.name}"), body_of(item), function_locals(item, owner))
                    module_level += item.decorator_list
                else:
                    module_level.append(item)
            module_level += [*node.decorator_list, *node.bases]
        elif not isinstance(node, ast.Import | ast.ImportFrom):
            module_level.append(node)
    scan(_MODULE, module_level, {})
    return tuple(effects.values()), tuple(calls.values())


def _dotted(expr: ast.expr, scope: dict[str, str]) -> str | None:
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
            return ".".join([base, *reversed(parts)]) if base else None
        else:
            return None


def _references(tree: ast.Module, unit: UnitName, package: UnitName, path: SourcePath, lines: list[str]):
    """Each name on one line that resolves to a dotted target: imported or defined names, attributes of
    typed parameters and of `self`, and the parameters themselves (as values of their type)."""
    module_names = _bindings(tree, unit, package)

    def column(line: int, offset: int) -> Column:
        text = lines[line - 1] if 0 < line <= len(lines) else ""
        return Column(offset if text.isascii() else len(text.encode()[:offset].decode(errors="ignore")))

    def emit(nodes, local: dict[str, str]):
        scope, values = {**module_names, **local}, set(local)
        for root in nodes:
            for node in ast.walk(root):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    if (typ := _dotted(node.value.func, scope)) is not None:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                scope[target.id], _ = typ, values.add(target.id)
                if not (isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load)):
                    continue
                if node.end_lineno != node.lineno or (target := _dotted(node, scope)) is None:
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
        local: dict[str, str] = {}
        params = [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]
        for i, a in enumerate(params):
            if i == 0 and owner and a.arg in ("self", "cls"):
                local[a.arg] = owner
            elif a.annotation is not None and (typ := _annotation_type(a.annotation, module_names)):
                local[a.arg] = typ
        yield from emit(signature_parts(fn), {})
        yield from emit([*fn.body, *fn.args.defaults, *(d for d in fn.args.kw_defaults if d is not None)], local)

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


def _annotation_type(annotation: ast.expr, names: dict[str, str]) -> str | None:
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
        return ".".join([names[annotation.id], *reversed(parts)])
    return None


def _open_mode(node: ast.Call, offset: int = 1) -> Effect:
    """`open(path, mode)` (offset 1) or `path.open(mode)` (offset 0): writing modes are fs.write."""
    mode = node.args[offset] if len(node.args) > offset else next((k.value for k in node.keywords if k.arg == "mode"), None)
    if mode is None:
        return Effect.FS_READ
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return Effect.FS_WRITE if set(mode.value) & set("wax+") else Effect.FS_READ
    return Effect.FS_WRITE  # unknown mode: assume the stronger effect


def _aliases(tree: ast.Module, unit: UnitName, package: UnitName, at):
    """Names this module binds at the top level by importing them from elsewhere; public if in __all__."""
    names = _bindings(tree, unit, package)
    exported = _dunder_all(tree) or frozenset()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    local = a.asname or a.name
                    exposure = Exposure.PUBLIC if local in exported else Exposure.INTERNAL
                    yield Alias(unit, SymbolName(local), Text(names[local]), at(node), exposure)


def _parameters(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[Parameter, ...]:
    a = fn.args
    positional = [*a.posonlyargs, *a.args]
    defaulted = {arg.arg for arg in positional[len(positional) - len(a.defaults):]} if a.defaults else set()
    defaulted |= {arg.arg for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None}
    extra = [x for x in (a.vararg, a.kwarg) if x is not None]
    args = [*positional, *a.kwonlyargs, *extra]
    if args and args[0].arg in ("self", "cls"):
        args = args[1:]
    optional = defaulted | {x.arg for x in extra}
    return tuple(Parameter(Text(x.arg), _type_ref(x.annotation),
                           Optionality.OPTIONAL if x.arg in optional else Optionality.REQUIRED) for x in args)


def _type_ref(annotation: ast.expr | None) -> TypeRef | None:
    if annotation is None:
        return None
    return TypeRef(Text(ast.unparse(annotation)), frozenset(Text(n) for n in _leaves(annotation)))


_TYPING_PREFIXES = ("typing.", "builtins.", "collections.abc.", "typing_extensions.")


def _leaves(node: ast.expr) -> set[str]:
    """Type names in leaf position; container names (the part before `[`) are not leaves."""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        name = ast.unparse(node)
        for prefix in _TYPING_PREFIXES:
            name = name.removeprefix(prefix)
        return {name}
    if isinstance(node, ast.Constant):
        if node.value is None:
            return {"None"}
        if isinstance(node.value, str):  # a string annotation
            try:
                return _leaves(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                return {node.value}
        return set()  # Ellipsis and literals
    if isinstance(node, ast.Subscript):
        container = ast.unparse(node.value)
        if container.split(".")[-1] in ("Literal", "Annotated"):
            return _leaves(node.slice.elts[0]) if container.endswith("Annotated") and isinstance(node.slice, ast.Tuple) else set()
        return _leaves(node.slice)
    if isinstance(node, ast.Tuple | ast.List):
        return set().union(*(_leaves(e) for e in node.elts)) if node.elts else set()
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _leaves(node.left) | _leaves(node.right)
    return {ast.unparse(node)}
