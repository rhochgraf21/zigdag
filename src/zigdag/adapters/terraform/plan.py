"""A rendered Terraform plan (`terraform show -json`), read for what it deploys: each resource the configuration
manages, and the resources each one references (DESIGN2 §5.3).

The plan's `configuration` is read, not its `planned_values`: the configuration names each resource once, however
many instances `count` or `for_each` make of it, and it alone records which expressions refer to what.

https://developer.hashicorp.com/terraform/internals/json-format
"""

from __future__ import annotations

import json
import posixpath
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

import deal

from zigdag.core.codec import Unreadable
from zigdag.core.findings import RecordPath
from zigdag.core.names import CodePath, Identifier
from zigdag.core.texts import FileText, Say, Written

_SUPPORTED_FORMAT = "1."  # the plan format's major version this reads; a later major may mean something else
_MANAGED = "managed"  # a resource Terraform creates, as against a data source, which reads one that exists
_MODULE, _VARIABLE, _LOCAL, _DATA = "module", "var", "local", "data"
# What a reference can start with that names nothing here: values Terraform supplies.
_NOT_DEPLOYED = frozenset({"each", "count", "path", "terraform", "self"})
POLICY_DOCUMENT = "aws_iam_policy_document"  # the data source that writes an IAM policy as blocks, not as text
_ALLOW = "Allow"  # what a policy statement does unless it says it denies
_LOCAL_SOURCES = ("./", "../")  # how a module's source is written when it is a folder of this project
_REFERENCES = "references"


@dataclass(frozen=True)
class Reached:
    """What an expression refers to, once its references are followed."""

    resources: tuple[CodePath, ...] = ()  # managed resources, in order of address
    data: tuple[CodePath, ...] = ()  # data sources, by address: data.aws_iam_policy_document.api
    untraced: tuple[Written, ...] = ()  # references that could not be followed: local values


@dataclass(frozen=True)
class PolicyStatement:
    """One statement of a policy document that allows."""

    actions: tuple[Written, ...]  # as written: s3:PutObject; empty when they are not written as constants
    on: Reached  # the resources it allows them on
    everything: bool  # its resources are constants, such as "*": no resource here is named


@dataclass(frozen=True)
class PolicyDocument:
    """A policy written as a data source (aws_iam_policy_document), whose statements the plan spells out."""

    address: CodePath  # data.aws_iam_policy_document.api, with its modules
    statements: tuple[PolicyStatement, ...]


@dataclass(frozen=True)
class Resource:
    """One resource the configuration manages."""

    address: CodePath  # as the plan names it, with its modules and without an instance's index: module.net.aws_vpc.main
    type: Identifier  # aws_s3_bucket
    name: Identifier  # site
    modules: tuple[Identifier, ...]  # the module calls it is inside, outermost first; none for the root module
    folder: RecordPath | None  # where its module's source is; None when the module is not a folder of this project
    references: tuple[CodePath, ...]  # the resources its expressions refer to, in order of address
    untraced: tuple[Written, ...]  # references that could not be followed: local values, which the plan leaves out
    arguments: Mapping[Identifier, Reached] = field(default_factory=dict)  # what each of its arguments refers to
    constants: Mapping[Identifier, Written] = field(default_factory=dict)  # its arguments that are plain text


@dataclass(frozen=True)
class Declared:
    """What one folder of source declares, as the plan has it: the resources it manages and the modules it calls."""

    folder: RecordPath
    resources: frozenset[tuple[Identifier, Identifier]]  # each by its type and its name
    calls: frozenset[Identifier]


@dataclass(frozen=True)
class Plan:
    resources: tuple[Resource, ...]
    declared: tuple[Declared, ...] = ()  # for each folder of this project that a module of the plan is written in
    documents: tuple[PolicyDocument, ...] = ()


@dataclass(frozen=True)
class _Module:
    """One module of the configuration, as it is called."""

    path: tuple[Identifier, ...]
    raw: Mapping
    folder: RecordPath | None
    parent: _Module | None
    arguments: Mapping  # the expressions its call gives its variables; empty for the root module

    @property
    def prefix(self) -> str:
        return "".join(f"{_MODULE}.{name}." for name in self.path)

    @property
    def managed(self) -> Iterator[Mapping]:
        for raw in self.raw.get("resources", ()):
            if isinstance(raw, Mapping) and raw.get("mode") == _MANAGED:
                yield raw

    @property
    def children(self) -> Iterator[_Module]:
        calls = self.raw.get("module_calls", {})
        for name, call in sorted(calls.items() if isinstance(calls, Mapping) else ()):
            if isinstance(call, Mapping) and isinstance(call.get("module"), Mapping):
                arguments = call.get("expressions", {})
                yield _Module((*self.path, Identifier(name)), call["module"], self._folder_of(call.get("source")), self,
                              arguments if isinstance(arguments, Mapping) else {})

    def _folder_of(self, source: object) -> RecordPath | None:
        if self.folder is None or not isinstance(source, str) or not source.startswith(_LOCAL_SOURCES):
            return None
        return RecordPath(posixpath.normpath(posixpath.join(self.folder, source)))

    def child(self, name: str) -> _Module | None:
        return next((m for m in self.children if m.path[-1] == name), None)

    def has(self, type_: str, name: str) -> bool:
        return any(r.get("type") == type_ and r.get("name") == name for r in self.managed)


def _written(expression: object) -> Iterator[str]:
    """Every reference an expression makes, however deep its blocks are nested."""
    if isinstance(expression, Mapping):
        for key, value in expression.items():
            if key == _REFERENCES and isinstance(value, list):
                yield from (v for v in value if isinstance(v, str))
            else:
                yield from _written(value)
    elif isinstance(expression, list):
        for item in expression:
            yield from _written(item)


@dataclass
class _Followed:
    """Where references lead, gathered while they are followed."""

    resources: set[CodePath] = field(default_factory=set)
    untraced: set[Written] = field(default_factory=set)
    data: set[CodePath] = field(default_factory=set)
    seen: set[tuple[tuple[Identifier, ...], str]] = field(default_factory=set)  # a reference back to itself ends

    @property
    def reached(self) -> Reached:
        return Reached(tuple(sorted(self.resources)), tuple(sorted(self.data)), tuple(sorted(self.untraced)))


def _follow(module: _Module, reference: str, into: _Followed) -> None:
    """Follow one reference, as it is written inside a module, to the resources it reaches: straight to a resource,
    out through a variable to what the module's caller passed, or in through a module's output to what that is made
    from."""
    if (module.path, reference) in into.seen:
        return
    into.seen.add((module.path, reference))
    parts = reference.split(".")
    head = parts[0]
    if head in _NOT_DEPLOYED:
        return
    if head == _DATA:
        if len(parts) > 2:
            into.data.add(CodePath(f"{module.prefix}{_DATA}.{parts[1]}.{parts[2]}"))
    elif head == _LOCAL:
        into.untraced.add(Written(".".join(parts[:2])))
    elif head == _VARIABLE:
        if module.parent is not None and len(parts) > 1:
            for outer in _written(module.arguments.get(parts[1])):
                _follow(module.parent, outer, into)
    elif head == _MODULE:
        # The bare module is listed beside each of its outputs that is used, and only an output says what is reached.
        child = module.child(parts[1]) if len(parts) > 2 else None
        if child is not None:
            outputs = child.raw.get("outputs", {})
            for inner in _written(outputs.get(parts[2]) if isinstance(outputs, Mapping) else None):
                _follow(child, inner, into)
    elif len(parts) > 1 and module.has(head, parts[1]):
        into.resources.add(CodePath(f"{module.prefix}{head}.{parts[1]}"))


def _resource(module: _Module, raw: Mapping) -> Resource | None:
    type_, name = raw.get("type"), raw.get("name")
    if not isinstance(type_, str) or not isinstance(name, str):
        return None
    address = CodePath(f"{module.prefix}{type_}.{name}")
    into = _Followed()
    depends_on = raw.get("depends_on", ())
    written = raw.get("expressions")
    expressions: Mapping = written if isinstance(written, Mapping) else {}
    others = (raw.get("count_expression"), raw.get("for_each_expression"))
    for reference in (*_written([expressions, *others]), *(d for d in depends_on if isinstance(d, str))):
        _follow(module, reference, into)
    return Resource(address, Identifier(type_), Identifier(name), module.path, module.folder,
                    tuple(sorted(into.resources - {address})), tuple(sorted(into.untraced)),
                    {Identifier(argument): _reached(module, expression) for argument, expression in expressions.items()},
                    {Identifier(argument): Written(expression["constant_value"])
                     for argument, expression in expressions.items()
                     if isinstance(expression, Mapping) and isinstance(expression.get("constant_value"), str)})


def _reached(module: _Module, expression: object) -> Reached:
    into = _Followed()
    for reference in _written(expression):
        _follow(module, reference, into)
    return into.reached


def _texts(expression: object) -> tuple[Written, ...]:
    """The texts an argument is, when it is written as constants: one, or a list of them."""
    value = expression.get("constant_value") if isinstance(expression, Mapping) else None
    values = value if isinstance(value, list) else [value]
    return tuple(Written(v) for v in values if isinstance(v, str))


def _documents(module: _Module) -> list[PolicyDocument]:
    found = []
    for raw in module.raw.get("resources", ()):
        if not isinstance(raw, Mapping) or raw.get("mode") != _DATA or raw.get("type") != POLICY_DOCUMENT:
            continue
        expressions = raw.get("expressions") if isinstance(raw.get("expressions"), Mapping) else {}
        blocks = expressions.get("statement", ())
        statements = []
        for block in (b for b in (blocks if isinstance(blocks, list) else ()) if isinstance(b, Mapping)):
            if (_texts(block.get("effect")) or (_ALLOW,))[0] != _ALLOW:
                continue  # a statement that denies grants nothing
            on = _reached(module, block.get("resources"))
            statements.append(PolicyStatement(_texts(block.get("actions")), on,
                                              not on.resources and bool(_texts(block.get("resources")))))
        found.append(PolicyDocument(CodePath(f"{module.prefix}{_DATA}.{POLICY_DOCUMENT}.{raw.get('name')}"),
                                    tuple(statements)))
    return found


def _modules(module: _Module) -> Iterator[_Module]:
    yield module
    for child in module.children:
        yield from _modules(child)


@deal.ensure(lambda text, root, result: isinstance(result, Unreadable) or all(
    set(r.references) <= {other.address for other in result.resources} for r in result.resources))
@deal.ensure(lambda text, root, result: isinstance(result, Unreadable) or len({r.address for r in result.resources})
             == len(result.resources))
def read_plan(text: FileText, root: RecordPath) -> Plan | Unreadable:
    """The resources a rendered plan's configuration manages, whose root module is written in the folder given. A plan
    with a resource that lacks its type or its name is refused whole, so that none is dropped unseen."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return Unreadable(Say(f"not JSON: {e}"))
    version = raw.get("format_version") if isinstance(raw, Mapping) else None
    if not isinstance(version, str) or not version.startswith(_SUPPORTED_FORMAT):
        return Unreadable(Say(f"not a plan as terraform show -json writes it (format {_SUPPORTED_FORMAT}x)"))
    configuration = raw.get("configuration", {})
    root_module = configuration.get("root_module", {}) if isinstance(configuration, Mapping) else None
    if not isinstance(root_module, Mapping):
        return Unreadable(Say("the plan's configuration has no root module"))
    resources: dict[CodePath, Resource] = {}
    declared: dict[RecordPath, Declared] = {}
    documents: list[PolicyDocument] = []
    for module in _modules(_Module((), root_module, root, None, {})):
        documents += _documents(module)
        if module.folder is not None:  # a folder called twice declares the same both times
            declared[module.folder] = Declared(
                module.folder,
                frozenset((Identifier(r["type"]), Identifier(r["name"])) for r in module.managed
                          if isinstance(r.get("type"), str) and isinstance(r.get("name"), str)),
                frozenset(child.path[-1] for child in module.children))
        for raw_resource in module.managed:
            resource = _resource(module, raw_resource)
            if resource is None:
                return Unreadable(Say(f"a resource in {module.prefix or 'the root module'} lacks its type or its name"))
            resources[resource.address] = resource
    return Plan(tuple(resources[address] for address in sorted(resources)),
                tuple(declared[folder] for folder in sorted(declared)), tuple(documents))
