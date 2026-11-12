"""Calls to the clients of deployed resources (DESIGN2 §5.3): a storage client's read or write, read from Python
for which resource it is on. The resource's name is the infrastructure's to give, so what is read here is the
setting the name comes from, such as an environment variable; which resource that is, the infrastructure says.

Only boto3's clients are read. A database connection's statements wait for the SQL adapter.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass, field

from zigdag.core.code import ResourceAccess
from zigdag.core.names import Api, Identifier

CLIENT_MAKERS = frozenset({"boto3.client", "boto3.resource"})
# How a boto3 method's name begins when it only reads; every other method changes what it is called on.
READS = ("get_", "list_", "head_", "describe_", "query", "scan", "batch_get_", "select_", "receive_", "download_")
# The arguments that name the resource a call is on, in boto3's own spelling.
RESOURCE_ARGUMENTS = frozenset({"Bucket", "TableName", "QueueUrl", "TopicArn", "FunctionName", "StreamName",
                                "SecretId", "StateMachineArn"})
_ENVIRON, _GET, _GETENV = "os.environ", "os.environ.get", "os.getenv"

Resolve = Callable[[ast.expr], "str | None"]  # an expression's qualified name, as the scanner works it out


@dataclass(frozen=True)
class ClientCall:
    """One call to a client of a deployed resource."""

    access: ResourceAccess
    via: Api  # s3.put_object
    setting: Identifier | None  # the environment variable the resource's name comes from, when it can be told


@dataclass
class Tracker:
    """What one file binds to a client of a deployed resource, and to a setting's value, as it is read top down."""

    resolve: Resolve
    clients: dict[str, str] = field(default_factory=dict)  # a name as written (s3, self.s3) -> the service it is of
    settings: dict[str, Identifier] = field(default_factory=dict)  # a name as written -> the setting it holds

    def _service(self, value: ast.expr) -> str | None:
        """The service a value is a client of: what boto3.client("s3") makes, or a name bound to one."""
        if isinstance(value, ast.Call) and self.resolve(value.func) in CLIENT_MAKERS:
            first = value.args[0] if value.args else None
            return first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
        return self.clients.get(ast.unparse(value)) if isinstance(value, ast.Name | ast.Attribute) else None

    def setting_of(self, value: ast.expr) -> Identifier | None:
        """The environment variable a value is read from: os.environ["X"], os.environ.get("X"), os.getenv("X"), or
        a name bound to one of them."""
        named: ast.expr | None = None
        if isinstance(value, ast.Subscript) and self.resolve(value.value) == _ENVIRON:
            named = value.slice
        elif isinstance(value, ast.Call) and self.resolve(value.func) in (_GET, _GETENV) and value.args:
            named = value.args[0]
        elif isinstance(value, ast.Name | ast.Attribute):
            return self.settings.get(ast.unparse(value))
        return Identifier(named.value) if isinstance(named, ast.Constant) and isinstance(named.value, str) else None

    def assigned(self, target: ast.expr, value: ast.expr) -> None:
        """Note what an assignment binds its target to, and forget what the target was bound to before."""
        if not isinstance(target, ast.Name | ast.Attribute):
            return
        name = ast.unparse(target)
        service, setting = self._service(value), self.setting_of(value)
        self.clients.pop(name, None)
        self.settings.pop(name, None)
        if service is not None:
            self.clients[name] = service
        if setting is not None:
            self.settings[name] = setting

    def call(self, node: ast.Call) -> ClientCall | None:
        """The call as one to a client of a deployed resource, or None when it is not one."""
        if not isinstance(node.func, ast.Attribute):
            return None
        service = self._service(node.func.value)
        if service is None:
            return None
        method = node.func.attr
        on = next((k.value for k in node.keywords if k.arg in RESOURCE_ARGUMENTS), None)
        return ClientCall(ResourceAccess.READ if method.startswith(READS) else ResourceAccess.WRITE,
                          Api(f"{service}.{method}"), self.setting_of(on) if on is not None else None)
