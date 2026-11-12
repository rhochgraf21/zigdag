"""Who may do what to what, as a Terraform project says it (DESIGN2 §5.3): the access its policies grant, the
settings that point one resource at another, and the network rules that let one reach another.

Grants and network rules are read from the plan, which spells out which resources each argument refers to. A
policy's actions are read where the plan has them as constants: in a policy document written as a data source. A
policy written as text holds its actions inside the text, which the plan cannot give before it is applied, so its
statements are read from the source (policy_text); where they cannot be, the grant is access that could not be told.

Settings are read from the source: an environment variable's name is written inside a map or an encoded text, where
the plan records only that the whole of it refers to some resources, not which name refers to which.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import deal

from zigdag.adapters.terraform import policy_text
from zigdag.adapters.terraform.plan import Plan, PolicyDocument, Reached, Resource
from zigdag.core.code import Grant, ResourceAccess, Setting
from zigdag.core.findings import Span
from zigdag.core.names import CodePath, Identifier
from zigdag.core.texts import Written

# How an action's name begins when it only reads; every other action changes what it is granted on.
READS = ("Get", "List", "Describe", "Head", "Query", "Scan", "BatchGet", "Select", "Receive", "Read", "Lookup",
         "Search", "View")
_ANY = "*"
INLINE_POLICY = Written("a policy written as text")  # what a grant's action is called when it could not be read

_ROLE_POLICY, _POLICY, _ATTACHMENT, _ROLE = ("aws_iam_role_policy", "aws_iam_policy",
                                            "aws_iam_role_policy_attachment", "aws_iam_role")
SECURITY_GROUP, _GROUP_RULE = "aws_security_group", "aws_security_group_rule"
_INGRESS_RULE, _EGRESS_RULE = "aws_vpc_security_group_ingress_rule", "aws_vpc_security_group_egress_rule"
_INGRESS, _EGRESS = Identifier("ingress"), Identifier("egress")
# The arguments of a security group that are network rules: what they refer to may reach it, or be reached from it.
CONNECTING = frozenset({_INGRESS, _EGRESS})


@deal.post(lambda result: 1 <= len(result) <= len(ResourceAccess))
def access_of(action: Written) -> tuple[ResourceAccess, ...]:
    """What an action lets its holder do: read, write, or both when it is written with a wildcard that covers
    both, as s3:* is."""
    name = action.rpartition(":")[2]
    stem = name.rstrip(_ANY)
    if not stem:
        return (ResourceAccess.READ, ResourceAccess.WRITE)
    return (ResourceAccess.READ,) if stem.startswith(READS) else (ResourceAccess.WRITE,)


@dataclass(frozen=True)
class Unread:
    """A grant that names no resource here: its resources are constants, such as "*"."""

    by: CodePath  # the policy
    actions: tuple[Written, ...]


def _argument(resource: Resource, name: str) -> Reached:
    return resource.arguments.get(Identifier(name), Reached())


BlockLines = Mapping[CodePath, Sequence[str]]  # each resource whose block was found in the source, with its lines


def _beside(plan: Plan, resource: Resource) -> frozenset[tuple[Identifier, Identifier]]:
    """The resources of a resource's own module, each by type and name: what its block can refer to directly."""
    return frozenset((r.type, r.name) for r in plan.resources if r.modules == resource.modules)


def _as_text(plan: Plan, resource: Resource, written: BlockLines) -> tuple[policy_text.Statement, ...] | None:
    """What a policy written as text in a resource's block allows; None when its block was not found or cannot be
    read for certain."""
    lines = written.get(resource.address)
    return policy_text.statements(lines, _beside(plan, resource)) if lines is not None else None


def _policy_grants(plan: Plan, holder: Resource, roles: Iterable[CodePath], policy: Reached,
                   documents: Mapping[CodePath, PolicyDocument], written: BlockLines, span: Span) -> list[Grant]:
    """What a policy grants each role it is given to. A policy document's statements are the plan's to give: each
    action, on each resource the statement names. A policy written as text is read from the source; a resource the
    policy refers to that no statement read from it names is granted access that could not be read."""
    prefix = "".join(f"module.{m}." for m in holder.modules)
    found = []
    for role in sorted(roles):
        read: set[CodePath] = set()
        for document in (documents[d] for d in policy.data if d in documents):
            found += [Grant(role, on, access, action, span) for statement in document.statements
                      for on in statement.on.resources for action in statement.actions
                      for access in access_of(action)]
        for statement in (_as_text(plan, holder, written) or ()) if not policy.data else ():
            named = [CodePath(f"{prefix}{type_}.{name}") for type_, name in statement.on]
            read.update(named)
            found += [Grant(role, on, access, action, span) for on in named for action in statement.actions
                      for access in access_of(action)]
        found += [Grant(role, on, None, INLINE_POLICY, span) for on in policy.resources if on != role and on not in read]
    return found


def _policies(plan: Plan) -> list[tuple[Resource, tuple[CodePath, ...], Reached]]:
    """Each resource that holds a policy, with the roles the policy is given to and what the policy refers to: a
    role's own policy, a managed policy with the roles it is attached to, and a role with policies written in it."""
    attached: dict[CodePath, set[CodePath]] = {}  # a managed policy -> the roles it is attached to
    for resource in plan.resources:
        if resource.type == _ATTACHMENT:
            for policy in _argument(resource, "policy_arn").resources:
                attached.setdefault(policy, set()).update(_argument(resource, "role").resources)
    found = []
    for resource in plan.resources:
        if resource.type == _ROLE_POLICY:
            found.append((resource, _argument(resource, "role").resources, _argument(resource, "policy")))
        elif resource.type == _POLICY:
            found.append((resource, tuple(sorted(attached.get(resource.address, ()))), _argument(resource, "policy")))
        elif resource.type == _ROLE:
            found.append((resource, (resource.address,), _argument(resource, "inline_policy")))
    return found


@deal.ensure(lambda plan, spans, written, result: all(g.to != g.on for g in result))
def grants(plan: Plan, spans: Mapping[CodePath, Span], written: BlockLines) -> tuple[Grant, ...]:
    """The access the plan's policies grant to its roles: a role's own policies, and the policies attached to it."""
    documents = {d.address: d for d in plan.documents}
    found: list[Grant] = []
    for holder, roles, policy in _policies(plan):
        found += _policy_grants(plan, holder, roles, policy, documents, written, spans[holder.address])
    return tuple(g for g in dict.fromkeys(found) if g.to != g.on)


@deal.ensure(lambda plan, written, result: all(u.actions for u in result))
def unread(plan: Plan, written: BlockLines) -> tuple[Unread, ...]:
    """The grants whose resources are constants, by the policy that makes them: a policy document, or a policy
    written as text."""
    in_documents = [Unread(d.address, s.actions) for d in plan.documents for s in d.statements
                    if s.everything and s.actions]
    as_text = [Unread(holder.address, s.actions) for holder, _, policy in _policies(plan) if not policy.data
               for s in (_as_text(plan, holder, written) or ()) if s.everything]
    return (*in_documents, *as_text)


@deal.ensure(lambda plan, result: all(a != b for a, b in result))
def connections(plan: Plan) -> tuple[tuple[CodePath, CodePath], ...]:
    """Each pair of security groups where the first may reach the second, by a rule of its own or one written
    inside a group."""
    found: list[tuple[CodePath, CodePath]] = []
    for resource in plan.resources:
        here = _argument(resource, "security_group_id").resources
        if resource.type == SECURITY_GROUP:
            found += [(other, resource.address) for other in _argument(resource, _INGRESS).resources]
            found += [(resource.address, other) for other in _argument(resource, _EGRESS).resources]
        elif resource.type == _GROUP_RULE:
            others = _argument(resource, "source_security_group_id").resources
            inward = resource.constants.get(Identifier("type")) != _EGRESS
            found += [(o, h) if inward else (h, o) for h in here for o in others]
        elif resource.type == _INGRESS_RULE:
            found += [(o, h) for h in here for o in _argument(resource, "referenced_security_group_id").resources]
        elif resource.type == _EGRESS_RULE:
            found += [(h, o) for h in here for o in _argument(resource, "referenced_security_group_id").resources]
    return tuple(pair for pair in dict.fromkeys(found) if pair[0] != pair[1])


_MAP_OPENS = re.compile(r"\bvariables\s*=\s*\{")  # the map of a function's environment variables
_ENTRY = re.compile(r"\s*\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s*=\s*(.+)$")
_NAMED = re.compile(r"\bname\s*=\s*\"([^\"]+)\"")  # a setting written as a pair, as a container's environment is
_VALUED = re.compile(r"\bvalue\s*=\s*(.+)$")
_REFERENCE = re.compile(r"\b([a-z][a-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_-]*)")
_PAIR_REACH = 3  # lines from a pair's name to its value, as formatters lay a pair out


def _named_in(value: str, known: frozenset[tuple[str, str]]) -> tuple[str, str] | None:
    """The one resource of the module that a written value refers to, or None when it is none or several."""
    referred = {(t, n) for t, n in _REFERENCE.findall(value) if (t, n) in known}
    return next(iter(referred)) if len(referred) == 1 else None


def _pairs(lines: list[str]) -> list[tuple[str, str]]:
    """Each setting a block writes, with the value it is given: an entry of a variables map, or a name with its
    value."""
    found, inside = [], 0
    for at, line in enumerate(lines):
        if inside:
            entry = _ENTRY.match(line)
            if entry is not None and line.count("{") == line.count("}"):
                found.append((entry.group(1), entry.group(2)))
            inside += line.count("{") - line.count("}")
        elif _MAP_OPENS.search(line):
            inside = line.count("{") - line.count("}")
        named = _NAMED.search(line)
        if named is not None:
            after = [line[named.end():], *lines[at + 1:at + _PAIR_REACH]]  # the rest of its line, then the next
            valued = next((v for text in after if (v := _VALUED.search(text)) is not None), None)
            if valued is not None:
                found.append((named.group(1), valued.group(1)))
    return found


@deal.ensure(lambda resource, lines, known, span, result: all(s.at == resource.address for s in result))
def settings(resource: Resource, lines: list[str], known: frozenset[tuple[str, str]], span: Span) -> tuple[Setting, ...]:
    """The settings a resource's block gives it that point at another resource of its module: read from the lines
    of its block, each setting whose value refers to exactly one resource."""
    prefix = "".join(f"module.{m}." for m in resource.modules)
    found = []
    for name, value in _pairs(lines):
        target = _named_in(value, known)
        if target is not None and CodePath(f"{prefix}{target[0]}.{target[1]}") != resource.address:
            found.append(Setting(resource.address, Identifier(name), CodePath(f"{prefix}{target[0]}.{target[1]}"), span))
    return tuple(dict.fromkeys(found))
