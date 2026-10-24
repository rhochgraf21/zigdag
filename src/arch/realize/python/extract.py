"""Units, imports, public API, contracts and design links from Python source.

Realizes arch.realize.python.extract. Uses the stdlib `ast` and never imports or runs user code.
Effects are charged to the code that obtains access to an effectful API (see this component's
decisions), and calls are recorded so realize can propagate effects across the project.
"""

from __future__ import annotations

import ast

from arch.realize.facts import (
    Call,
    Capability,
    ContractDecl,
    DesignLink,
    Effect,
    EffectUse,
    Facts,
    Import,
    Language,
    LineNo,
    ParseError,
    PublicSymbol,
    Role,
    SourceLocation,
    SourcePath,
    SourceText,
    SymbolName,
    Text,
    Unit,
    UnitName,
)

LANGUAGE = Language("python")
CAPABILITIES = frozenset(Capability)
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

    exported = _dunder_all(tree)
    for node, qual in _definitions(tree):
        name = qual.rsplit(".", 1)[-1]
        top = "." not in qual
        public = (name in exported) if (exported is not None and top) else not name.startswith("_")
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and public:
            symbols.append(PublicSymbol(unit, SymbolName(qual), *_signature(node, qual), at(node)))
        elif isinstance(node, ast.Assign | ast.AnnAssign) and public and top and name != "__all__":
            symbols.append(PublicSymbol(unit, SymbolName(qual), Text("value"), Text(name), at(node)))
        for dec in getattr(node, "decorator_list", ()):
            if (kind := _contract_kind(dec, deal_names)) is not None:
                args = ", ".join(ast.unparse(a) for a in getattr(dec, "args", ())) if isinstance(dec, ast.Call) else ""
                contracts.append(ContractDecl(unit, SymbolName(qual), Text(kind), Text(args), at(dec)))
            for target in _realizes_targets(dec):
                links.append(DesignLink(unit, SymbolName(qual), Text(target), at(dec)))

    effects, calls = _effects_and_calls(tree, unit, package, at)
    return Facts(
        units=(Unit(unit, path, LANGUAGE, role, CAPABILITIES),),
        imports=imports,
        symbols=tuple(symbols),
        contracts=tuple(contracts),
        links=tuple(links),
        effects=effects,
        calls=calls,
    )


def _imports(tree: ast.Module, unit: UnitName, package: UnitName, at):
    """Every import anywhere in the module. `from x import y` targets `x.y`; consumers resolve the
    longest prefix that names a known unit, which covers both submodules and attributes."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield Import(unit, UnitName(alias.name), at(node))
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
                target = module if alias.name == "*" else ".".join(p for p in (module, alias.name) if p)
                yield Import(unit, UnitName(target), at(node))


def _definitions(tree: ast.Module):
    """Module-level and class-level definitions with qualified names (not nested functions)."""
    def walk(body, prefix):
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                yield node, prefix + node.name
            elif isinstance(node, ast.ClassDef):
                yield node, prefix + node.name
                yield from walk(node.body, prefix + node.name + ".")
            elif isinstance(node, ast.Assign) and not prefix:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        yield node, t.id
            elif isinstance(node, ast.AnnAssign) and not prefix and isinstance(node.target, ast.Name):
                yield node, node.target.id
    yield from walk(tree.body, "")


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
    calls: dict[tuple[SymbolName, str], Call] = {}

    def scan(symbol: SymbolName, nodes, local: dict[str, str]) -> None:
        scope = {**module_names, **local}

        def dotted(expr: ast.expr) -> str | None:
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

        def effect(kind: Effect, node: ast.AST) -> None:
            effects.setdefault((symbol, kind), EffectUse(unit, symbol, kind, True, at(node)))

        def call(name: str, node: ast.AST) -> None:
            calls.setdefault((symbol, name), Call(unit, symbol, Text(name), at(node)))

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
