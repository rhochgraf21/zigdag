"""Units, imports, public API, contracts and design links from Python source.

Realizes arch.realize.python.extract. Uses the stdlib `ast` and never imports or runs user code.
Effects are not analyzed yet, so units do not claim that capability (checks report "not analyzed").
"""

from __future__ import annotations

import ast

from arch.realize.facts import (
    Capability,
    ContractDecl,
    DesignLink,
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
CAPABILITIES = frozenset({Capability.STRUCTURE, Capability.API, Capability.CONTRACTS, Capability.LINKS})
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
            symbols.append(PublicSymbol(unit, SymbolName(qual), *_signature(node), at(node)))
        elif isinstance(node, ast.Assign | ast.AnnAssign) and public and top and name != "__all__":
            symbols.append(PublicSymbol(unit, SymbolName(qual), Text("value"), Text(name), at(node)))
        for dec in getattr(node, "decorator_list", ()):
            if (kind := _contract_kind(dec, deal_names)) is not None:
                args = ", ".join(ast.unparse(a) for a in getattr(dec, "args", ())) if isinstance(dec, ast.Call) else ""
                contracts.append(ContractDecl(unit, SymbolName(qual), Text(kind), Text(args), at(dec)))
            for target in _realizes_targets(dec):
                links.append(DesignLink(unit, SymbolName(qual), Text(target), at(dec)))

    return Facts(
        units=(Unit(unit, path, LANGUAGE, role, CAPABILITIES),),
        imports=imports,
        symbols=tuple(symbols),
        contracts=tuple(contracts),
        links=tuple(links),
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


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> tuple[Text, Text]:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in (*node.bases, *node.keywords))
        return Text("class"), Text(f"class {node.name}({bases})" if bases else f"class {node.name}")
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return Text("function"), Text(f"{prefix}{node.name}({ast.unparse(node.args)}){returns}")


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
